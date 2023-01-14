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

    str_update = dt_update.strftime("%Y/%m/%d %H:%M")
    data = {"lastUpdate": str_update}
    tag = soup.select_one("#tmp_contents > div > div.outline > ul")

    # 人数取得
    text = tag.get_text(strip=True)

    temp = {}

    for i in re.finditer(
        r"(入院|陽性確認者数|新規公表分|指定医療機関|一般医療機関|最重症者|重症者|宿泊療養|自宅療養|宿泊療養予定\(宿泊療養施設への入室予定として調整している者\)|入院予定・宿泊療養等調整中\(入院予定として調整している者のほか宿泊療養等を調整中の者\)|新型コロナウイルス感染症を死因とする死亡|死亡|新規公表分|退院・療養終了)：?([0-9,]+)人?",
        text,
    ):
        temp[i.group(1)] = int(i.group(2).replace(",", ""))

    for i in re.finditer(
        r"(一般医療機関)?([0-9,]+)人?",
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

    temp["現在の患者数"] = "-"
    temp["自宅療養等"] = "-"

    # 入院中
    temp["入院中"] = temp["指定医療機関"] + temp["一般医療機関"]

    # main_summary.json
    main_summary = {
        "attr": "検査実施人数",
        "value": "-",
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
                    {"attr": "退院・療養終了", "value": "-"},
                ],
            }
        ],
        "lastUpdate": str_update,

    }
    dumps_json("main_summary.json", main_summary, "data")

    # 陽性者数推移
    export_patients_summary_json(str_update)    

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

def export_patients_summary_json(update_date):
    url = settings.PATIENTS_SUMMARY_URL
    text = settings.PATIENTS_SUMMARY_TITLE

    soup = fetch_soup(url)
    csv_href = soup.find_all("a", text=re.compile(text))[-1].get("href")

    path = fetch_file(urljoin(url, csv_href), "download")

    # 日付,新規陽性者数,陽性者数累計
    df = pd.read_csv(path, encoding="cp932")
    try:
        df.dropna(subset=["日付"], inplace=True)

        df["日付"] = pd.to_datetime(df["日付"], errors="coerce")
        df["日付"] = df["日付"].dt.strftime("%Y-%m-%dT08:00:00.000Z")
        df.rename(columns={"新規陽性者数": "小計"}, inplace=True)
        df.drop(columns="陽性者数累計", inplace=True)
        df["うちみなし陽性者数"] = df["うちみなし陽性者数"].fillna(0)
        df.drop(columns="うちみなし陽性者数累計", inplace=True)
        patients_summary = {
            "data": df.to_dict(orient="records"),
            "date": update_date,
        }

        dumps_json("patients_summary.json", patients_summary, "data")
    except KeyError as e:
        print(e)

# main
if __name__ == "__main__":
    # export data.json
    export_data_json()

    # export news.json
    export_news_json()
