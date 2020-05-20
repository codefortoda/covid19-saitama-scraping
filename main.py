import datetime
import json
import pandas as pd
import pathlib
import requests
import re
from bs4 import BeautifulSoup
from retry import retry
from urllib.parse import urljoin

# settings
import settings

@retry(tries=5, delay=5, backoff=3)
def get_file(url, dir="."):
    r = requests.get(url, headers=settings.REQUEST_HEADERS)

    p = pathlib.Path(dir, pathlib.PurePath(url).name)
    p.parent.mkdir(parents=True, exist_ok=True)

    with p.open(mode='wb') as fw:
        fw.write(r.content)

    return p

def csv_link(url):
    r = requests.get(url, headers=settings.REQUEST_HEADERS)
    r.raise_for_status()

    soup = BeautifulSoup(r.content, "html.parser")

    link = soup.find("p", class_="muted ellipsis").find("a").get("href")

    return link

def get_csv(url, text):
    r = requests.get(url, headers=settings.REQUEST_HEADERS)
    r.raise_for_status()

    soup = BeautifulSoup(r.content, "html.parser")

    href = soup.find_all("a", title=re.compile(text))[-1].get("href")

    link = csv_link(urljoin(url, href))

    p = get_file(link, settings.DOWNLOAD_DIR)

    return p

def export_data_json():
    # main_summary
    r = requests.get(settings.MAIN_SUMMARY_URL)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, "html.parser")
    tag = soup.find("div", class_="box_info_ttl")

    # 更新日付取得
    s_date = tag.find("span", class_="txt_big").get_text(strip=True)
    l_date = list(map(int, re.findall("(\d{1,2})", s_date)))

    dt_now = datetime.datetime.now()
    dt_update = datetime.datetime(dt_now.year, *l_date, 21, 0).strftime("%Y/%m/%d %H:%M")
    data = {"lastUpdate": dt_update}
    data["lastUpdate"] = dt_update

    # 人数取得
    main_sum = [int(i.replace(",", "")) for i in re.findall("([0-9,]+)人", tag.get_text())]

    data["main_summary"] = {
        "attr": "検査実施人数",
        "value": main_sum[9],
        "children": [
            {
                "attr": "陽性患者数",
                "value": main_sum[0],
                "children": [
                    {
                        "attr": "入院中",
                        "value": main_sum[2] + main_sum[4] + main_sum[5] + main_sum[8],
                        "children": [
                            {"attr": "軽症・中等症", "value": main_sum[2] - main_sum[3]  + main_sum[4] + main_sum[5] + main_sum[8]},
                            {"attr": "重症", "value": main_sum[3]},
                        ],
                    },
                    {"attr": "退院", "value": main_sum[6]},
                    {"attr": "死亡", "value": main_sum[7]},
                ],
            }
        ],
    }

    jokyo_path = get_csv(settings.JOKYO_URL, settings.JOKYO_TITLE)
    df_kanja = pd.read_csv(jokyo_path, encoding="cp932")
    df_kanja["date"] = df_kanja["判明日"].apply(
        lambda x: pd.to_datetime(x, errors="coerce")
        if x.startswith("202")
        else pd.to_datetime(x, format="%y/%m/%d", errors="coerce")
    )
    df_patients_sum = (
        df_kanja["date"].value_counts().sort_index().asfreq("D", fill_value=0).reset_index()
    )

    df_patients_lastdate = df_patients_sum.iloc[-1]["index"]
    lastdate = datetime.datetime(dt_now.year, *l_date)
    while df_patients_lastdate < lastdate:
        df_patients_lastdate += datetime.timedelta(days=1)
        s = pd.Series([df_patients_lastdate, 0], index=df_patients_sum.columns)
        df_patients_sum = df_patients_sum.append(s, ignore_index=True)

    df_patients_sum["日付"] = df_patients_sum["index"].dt.strftime("%Y-%m-%dT08:00:00.000Z")
    df_patients_sum.rename(columns={"date": "小計"}, inplace=True)
    df_patients_sum.drop(columns=["index"], inplace=True)
    data["patients_summary"] = {
        "data": df_patients_sum.to_dict(orient="records"),
        "date": dt_update,
    }
    df_kanja.rename(columns={"NO.": "No"}, inplace=True)
    df_kanja["リリース日"] = df_kanja["date"].dt.strftime("%Y-%m-%dT08:00:00.000Z")
    df_kanja["date"] = df_kanja["date"].dt.strftime("%Y-%m-%d")
    df_kanja["リリース日"] = df_kanja["リリース日"].mask(df_kanja["判明日"] == "調査中", "調査中")
    df_kanja["date"] = df_kanja["date"].mask(df_kanja["判明日"] == "調査中", "調査中")
    df_kanja["退院"] = ""

    df_patients = df_kanja.loc[:, ["No", "リリース日", "年代", "性別", "居住地", "退院", "date"]].copy()
    df_patients.fillna("", inplace=True)

    data["patients"] = {
        "data": df_patients.to_dict(orient="records"),
        "date": dt_update,
    }

    kensa_path = get_csv(settings.KENSA_URL, settings.KENSA_TITLE)
    df_kensa = pd.read_csv(kensa_path, encoding="cp932", index_col="検査日", parse_dates=True)
    df_kensa.rename(columns={"検査数（延べ人数）": "小計"}, inplace=True)
    df_kensa["日付"] = df_kensa.index.strftime("%Y-%m-%dT08:00:00.000Z")
    df_insp_sum = df_kensa.loc[:, ["日付", "小計"]]
    data["inspections_summary"] = {
        "data": df_insp_sum.to_dict(orient="records"),
        "date": dt_update,
    }

    p = pathlib.Path(settings.DATA_DIR, "data.json")
    p.parent.mkdir(parents=True, exist_ok=True)

    with p.open(mode="w", encoding="utf-8") as fw:
        json.dump(data, fw, ensure_ascii=False, indent=4)

def export_news_json():

    r = requests.get(settings.NEWS_URL)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, "html.parser")

    boxnews = soup.find(class_="box_news")
    ullist = boxnews.ul.find_all("li")

    newslist = settings.NEWS_LIST

    for li in ullist:
        url = "https://www.pref.saitama.lg.jp" + li.a.get("href")
        text = li.a.get_text()
        if (text.startswith("新型コロナウイルスに関連した患者等の発生について")):
            match = re.search("([0-9]+)月([0-9]+)日", li.get_text())

            dt_now = datetime.datetime.now()
            date = datetime.datetime(dt_now.year, int(match.group(1)), int(match.group(2))).strftime("%Y/%m/%d")
        
            news = {"date": date, "url": url, "text": text}
            newslist["newsItems"].insert(0, news)
            
            break;

    p = pathlib.Path(settings.DATA_DIR, "news.json")
    p.parent.mkdir(parents=True, exist_ok=True)

    with p.open(mode="w", encoding="utf-8") as fw:
        json.dump(newslist, fw, ensure_ascii=False, indent=4)

# main
if __name__ == "__main__":
    # export data.json
    export_data_json()

    # export news.json
    export_news_json()
