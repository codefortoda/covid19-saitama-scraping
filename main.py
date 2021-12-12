import datetime
import json
import pathlib
import re
from collections import Counter
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

import settings

def fetch_soup(url):
    r = requests.get(url)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, "html.parser")

    return soup

def fetch_file(url, dir="."):
    p = pathlib.Path(dir, pathlib.PurePath(url).name)
    p.parent.mkdir(parents=True, exist_ok=True)

    # 同一ファイル名の場合はダウンロードしない
    if not p.exists():
        r = requests.get(url)
        with p.open(mode="wb") as fw:
            fw.write(r.content)

    return p

def fetch_csv(url, text):
    soup = fetch_soup(url)
    href = soup.find_all("a", title=re.compile(text))[-1].get("href")

    csv_soup = fetch_soup(urljoin(url, href))
    csv_href = csv_soup.find("p", class_="muted ellipsis").find("a").get("href")

    p = fetch_file(csv_href, "download")

    return p

def str2date(s):
    lst = list(map(int, re.findall("\d+", s)))
    lst.insert(0, None)

    return lst[-3:]

def dumps_json(file_name, json_data, dir="."):
    p = pathlib.Path(dir, file_name)
    p.parent.mkdir(parents=True, exist_ok=True)

    with p.open(mode="w") as fw:
        json.dump(json_data, fw, ensure_ascii=False, indent=4)

def export_data_json():
    soup = fetch_soup(settings.MAIN_SUMMARY_URL)

    # 更新日付取得
    s = soup.select_one("#tmp_update").get_text()
    m = re.search("([0-9]+)月([0-9]+)日", s)

    month, day = map(int, m.groups())
    dt_now = datetime.datetime.now()
    dt_update = dt_now.replace(month=month, day=day, hour=21, minute=0, second=0, microsecond=0)

    if dt_now < dt_update:
        dt_update = dt_update.replace(year=dt_now.year -1)

    str_update = dt_update.strftime("%Y/%m/%d %H:%M")
    data = {"lastUpdate": str_update}
    tag = soup.select_one("#tmp_contents > div > div.outline > ul")

    # 人数取得
    text = tag.get_text(strip=True)

    temp = {}
    #print(text)

    for i in re.finditer(
        r"(陽性確認者数|新規公表分|指定医療機関|一般医療機関|最重症者|重症者|宿泊療養|自宅療養|宿泊療養予定\(宿泊療養施設への入室予定として調整している者\)|入院予定・宿泊療養等調整中\(入院予定として調整している者のほか宿泊療養等を調整中の者\)|新型コロナウイルス感染症を死因とする死亡|死亡|新規公表分|退院・療養終了)：?([0-9,]+)人?",
        text,
    ):
        temp[i.group(1)] = int(i.group(2).replace(",", ""))

    for i in re.finditer(r"(自治体による検査|民間検査機関等による検査)[\(（]\d{1,2}月\d{1,2}日?まで[\)）]：延べ([0-9,]+)人", text):
        temp[i.group(1)] = int(i.group(2).replace(",", ""))

    m = re.search("(入院)：(指定医療機関)([0-9,]+)人?\s*(一般医療機関)([0-9,]+)人\s*(計)([0-9,]+)人?", text)
    if m:
        temp[f"{m.group(1)}_{m.group(2)}"] = int(m.group(3).replace(",", ""))
        temp[f"{m.group(1)}_{m.group(4)}"] = int(m.group(5).replace(",", ""))
        temp[f"{m.group(1)}_{m.group(6)}"] = int(m.group(7).replace(",", ""))

    m = re.search("(退院・療養終了)：(退院)([0-9,]+)人?\s*(療養終了)([0-9,]+)人\s*(計)：([0-9,]+)人?", text)
    if m:
        temp[f"{m.group(1)}_{m.group(2)}"] = int(m.group(3).replace(",", ""))
        temp[f"{m.group(1)}_{m.group(4)}"] = int(m.group(5).replace(",", ""))
        temp[f"{m.group(1)}_{m.group(6)}"] = int(m.group(7).replace(",", ""))

    temp["現在の患者数"] = temp["陽性確認者数"] - temp["退院・療養終了_計"] - temp["死亡"]
    temp["自宅療養等"] = temp["自宅療養"] + temp["宿泊療養予定(宿泊療養施設への入室予定として調整している者)"] + temp["入院予定・宿泊療養等調整中(入院予定として調整している者のほか宿泊療養等を調整中の者)"]

    # 入院中
    hospital = [temp.get("入院_計"), temp["現在の患者数"] - temp["宿泊療養"] - temp["自宅療養等"] - temp["新規公表分"], temp["指定医療機関"] + temp["一般医療機関"]]
    h = [k for k, v in Counter(hospital).items() if v > 1]
    temp["入院中"] = h[0] if h else hospital[0]

    data["main_summary"] = {
        "attr": "検査実施人数",
        "value": temp["自治体による検査"],
        "children": [
            {
                "attr": "陽性患者数",
                "value": temp["陽性確認者数"],
                "children": [
                    {
                        "attr": "入院中",
                        "value": temp["入院中"],
                        "children": [
                            {
                                "attr": "軽症・中等症",
                                "value": temp["陽性確認者数"]
                                    - temp["退院・療養終了_計"]
                                    - temp["死亡"]
                                    - temp["最重症者"]
                                    - temp["重症者"],
                            },
                            {"attr": "重症", "value": temp["最重症者"] + temp["重症者"]},
                        ],
                    },
                    {"attr": "退院", "value": temp["退院・療養終了_計"]},
                    {"attr": "死亡", "value": temp["死亡"]},
                ],
            }
        ],
    }

    # main_summary.json
    main_summary = {
        "attr": "検査実施人数",
        "value": temp["自治体による検査"],
        "children": [
            {
                "attr": "陽性患者数",
                "value": temp["陽性確認者数"],
                "children": [
                    {
                        "attr": "入院中",
                        "value": temp["入院中"],
                        "children": [
                            {"attr": "重症", "value": temp["最重症者"] + temp["重症者"]},
                        ],
                    },
                    {"attr": "宿泊療養", "value": temp["宿泊療養"]},
                    {"attr": "自宅療養", "value": temp["自宅療養等"]},
                    {"attr": "新規公表分", "value": temp["新規公表分"]},
                    {"attr": "死亡", "value": temp["死亡"]},
                    {"attr": "退院・療養終了", "value": temp["退院・療養終了_計"]},
                ],
            }
        ],
        "lastUpdate": str_update,
    }

    dumps_json("main_summary.json", main_summary, "data")

    # 検査
    try:
        kensa_path = fetch_csv(settings.KENSA_URL, settings.KENSA_TITLE)
        df_kensa = pd.read_csv(kensa_path, encoding="cp932")
        df_kensa.dropna(subset=["検査日"], inplace=True)

        df_date = (
            df_kensa["検査日"]
            .astype("str")
            .str.normalize("NFKC")
            .apply(str2date)
            .apply(pd.Series)
            .rename(columns={0: "year", 1: "month", 2: "day"})
        )

        df_date["year"] = df_date["year"].replace({20: 2020, 21: 2021}).fillna(method="ffill")
        df_kensa["検査日"] = pd.to_datetime(df_date, errors="coerce")
        df_kensa = df_kensa.set_index("検査日")
        df_kensa.rename(columns={"検査数（延べ人数）": "小計"}, inplace=True)
        df_kensa["日付"] = df_kensa.index.strftime("%Y-%m-%dT08:00:00.000Z")
        df_insp_sum = df_kensa.loc[:, ["日付", "小計"]]

        data["inspections_summary"] = {
            "data": df_insp_sum.to_dict(orient="records"),
            "date": str_update,
        }
        kensa_last_date = df_kensa.index[-1]
    except Exception as e:
        print(e)
        data["inspections_summary"] = {}
        kensa_last_date = str_update

    # 状況
    jokyo_path = fetch_file(settings.JOKYO_DATA_URL, "download") # fetch_csv(settings.JOKYO_URL, settings.JOKYO_TITLE)
    df_kanja = pd.read_csv(jokyo_path, encoding="cp932")

    df_temp = (
        df_kanja["判明日"]
        .astype("str")
        .str.normalize("NFKC")
        .apply(str2date)
        .apply(pd.Series)
        .rename(columns={0: "year", 1: "month", 2: "day"})
    )
    df_temp["year"] = df_temp["year"].replace({20: 2020, 21: 2021}).fillna(method="ffill")

    df_kanja["date"] = pd.to_datetime(df_temp, errors="coerce")

    #チェック
    # 2020年より前を抽出
    df_kanja[df_kanja["date"] < datetime.datetime(2020, 1, 1)]
    # 未来の日付を抽出
    df_kanja[df_kanja["date"] > dt_now]
    # 日付が空で調査中、発生届取り下げ、東京都発表、重複でないものを抽出
    df_kanja[(df_kanja["date"].isna()) & ~((df_kanja["判明日"].isin(["調査中", "発生届取り下げ", "東京都発表"]) | df_kanja["判明日"].str.contains("重複", na=False)))]

    # patients_summary
    ser_patients_sum = df_kanja["date"].value_counts().sort_index()
    dt_range = pd.date_range(ser_patients_sum.index[0], kensa_last_date)
    ser_patients_sum = ser_patients_sum.reindex(index=dt_range, fill_value=0)
    df_patients_sum = pd.DataFrame({"小計": ser_patients_sum})
    df_patients_sum["日付"] = df_patients_sum.index.strftime("%Y-%m-%dT08:00:00.000Z")
    data["patients_summary"] = {
        "data": df_patients_sum.to_dict(orient="records"),
        "date": str_update,
    }

    # patients
    df_kanja.rename(columns={"NO.": "No"}, inplace=True)
    df_kanja["判明日"] = df_kanja["判明日"].fillna("調査中")
    df_kanja["リリース日"] = df_kanja["date"].dt.strftime("%Y-%m-%dT08:00:00.000Z")
    df_kanja["リリース日"] = df_kanja["リリース日"].mask(df_kanja["判明日"] == "調査中", "調査中")
    df_kanja["date"] = df_kanja["date"].dt.strftime("%Y-%m-%d")
    df_kanja["date"] = df_kanja["date"].mask(df_kanja["判明日"] == "調査中", "調査中").fillna("調査中")
    df_kanja["退院"] = ""
    df_patients = df_kanja.loc[:, ["No", "リリース日", "年代", "性別", "居住地", "退院", "date"]].copy()
    df_patients.dropna(subset=["リリース日"], inplace=True)
    df_patients.fillna("", inplace=True)
    data["patients"] = {
        "data": df_patients.to_dict(orient="records"),
        "date": str_update,
    }

    dumps_json("data.json", data, "data")

def export_news_json():
    newslist = settings.NEWS_LIST

    soup = fetch_soup(settings.NEWS_URL)
    boxnews = soup.find(class_="box_news")
    ullist = boxnews.ul.find_all("li")

    for li in ullist:
        url = "https://www.pref.saitama.lg.jp" + li.a.get("href")
        text = li.a.get_text()
        if (text.startswith("新型コロナウイルスに関連した患者等の発生について")):
            match = re.search("([0-9]+)月([0-9]+)日", li.get_text())

            dt_now = datetime.datetime.now()
            date = datetime.datetime(dt_now.year, int(match.group(1)), int(match.group(2))).strftime("%Y/%m/%d")
        
            news = {"date": date, "url": url, "text": text}
            newslist["newsItems"].insert(0, news)
            
            break

    dumps_json("news.json", newslist, "data")

# main
if __name__ == "__main__":
    # export data.json
    export_data_json()

    # export news.json
    export_news_json()
