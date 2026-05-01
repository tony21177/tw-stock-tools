#!/usr/bin/env python3
"""
概念主題的關鍵字字典：用於從新聞標題中匹配各概念。

每個概念列出多個關鍵字（中英混合），匹配「至少一個」即視為提及該概念。
關鍵字應該是該概念的標誌性詞彙，避免過度泛用導致誤判。

匹配規則：
  - 中文 / 含中文 / 長英文（>5 字）關鍵字：子字串匹配
  - 短 ASCII 關鍵字（≤5 字、全英文 / 數字）：必須前後都不是英文或數字
    避免「ESS」誤匹配「PharmaEssentia」、「ASIC」誤匹配「classic」這類問題
"""

import re

THEME_KEYWORDS = {
    "CPO_矽光子": [
        "CPO", "矽光子", "Co-Packaged", "光通訊", "光收發", "光模組",
        "三五族", "InP", "矽光", "光晶片",
    ],
    "AI伺服器_ODM": [
        "AI伺服器", "AI Server", "GB200", "GB300", "Blackwell", "Hopper",
        "輝達伺服器", "資料中心", "AI 機架", "DGX", "HGX", "Foxconn AI",
        "NVL", "AI 主板", "AI ODM", "伺服器組裝", "機架式伺服器",
    ],
    "AI伺服器_電源": [
        "伺服器電源", "PSU", "電源供應器", "DC-DC", "BBU", "備援電池",
        "資料中心電源", "整流器", "Rectifier", "電源模組", "OCP 電源",
    ],
    "AI伺服器_線材連接": [
        "高速連接", "Connector", "高速連接器", "Cable", "高速線材", "DAC",
        "AEC", "Backplane", "I/O 連接", "Twinax", "高速傳輸線",
    ],
    "NVIDIA供應鏈": [
        "輝達", "NVIDIA", "Jensen", "黃仁勳", "GB200", "GB300", "Blackwell",
        "Rubin", "GTC", "DGX", "NVL72", "NVL36", "Spectrum-X",
    ],
    "ASIC自研晶片": [
        "ASIC", "自研晶片", "自研 AI", "TPU", "Trainium", "MTIA",
        "客製化晶片", "AI 加速器", "雲端自研",
    ],
    "玻璃基板_TGV": [
        "玻璃基板", "TGV", "GCS", "Glass Substrate", "玻璃載板",
        "玻璃通孔",
    ],
    "先進封裝_CoWoS": [
        "CoWoS", "先進封裝", "Advanced Packaging", "晶圓級封裝",
        "InFO", "SoIC", "3D 封裝", "Hybrid Bonding",
    ],
    "HBM記憶體": [
        "HBM", "高頻寬記憶體", "DDR", "DRAM", "GDDR", "記憶體模組",
        "高速記憶體",
    ],
    "液冷散熱": [
        "液冷", "水冷", "散熱模組", "冷卻液", "Cold Plate",
        "Thermal", "VC", "均熱片", "散熱片", "Liquid Cooling",
    ],
    "重電_電網": [
        "重電", "電網", "變壓器", "輸配電", "電力設備", "智慧電網",
        "GIS", "高壓電", "GIS 開關", "強韌電網", "饋線",
    ],
    # 註：移除 "台電" — 台電會被無關公司新聞順帶提及（用電大戶、台電合約等）
    "軍工": [
        "軍工", "國防", "Defense", "軍用", "戰機", "導彈", "雷達",
        "潛艦", "海巡", "F-16", "天弓",
    ],
    "機器人_人形": [
        "人形機器人", "Humanoid", "Optimus", "Tesla 機器人", "雙足機器人",
        "Figure", "1X", "Boston Dynamics", "減速機", "滾珠螺桿", "諧波減速",
    ],
    "機器人_工業自動化": [
        "工業機器人", "工業自動化", "Industrial Robot", "AMHS", "AGV",
        "PLC", "工控", "智慧工廠", "Smart Factory", "服務型機器人",
        "協作機器人", "Cobot",
    ],
    "無人機": [
        "無人機", "UAV", "Drone", "無人載具", "軍規無人機",
        "穿越機", "FPV",
    ],
    "鋰電池_儲能": [
        "鋰電池", "儲能", "ESS", "Energy Storage", "儲能櫃",
        "電池模組", "BMS", "磷酸鋰鐵",
    ],
    "PCB_ABF": [
        "PCB", "ABF", "ABF 載板", "印刷電路板", "高階載板",
        "BT 載板", "硬板", "軟板",
    ],
    "矽智財_IP": [
        "矽智財", "IP", "Silicon IP", "RISC-V", "ARM IP",
        "IP 授權", "IC 設計服務",
    ],
    "量子運算": [
        "量子運算", "Quantum", "量子電腦", "量子位元", "Qubit",
        "量子糾錯",
    ],
    "低軌衛星": [
        "低軌衛星", "LEO", "衛星", "Starlink", "OneWeb",
        "衛星通訊", "Ka 頻", "Ku 頻",
    ],
    "CXO_生技代工": [
        "CDMO", "CRO", "CMO", "CXO", "生技代工",
        "新藥代工", "原料藥",
    ],
    "網通_5G": [
        "網通", "5G", "WiFi", "交換器", "Router", "網路設備",
        "Switch", "Open RAN", "白牌", "WiFi 7",
    ],
    "ADAS_智駕": [
        "ADAS", "智駕", "自駕", "L2", "L3", "Autonomous",
        "盲點偵測", "車道偏移", "前向碰撞",
    ],
    "綠能_太陽能": [
        "太陽能", "Solar", "太陽能光電", "光電案場", "光電廠",
        "PV", "綠能", "再生能源", "光電板", "屋頂型光電",
        "地面型光電", "電廠開發",
    ],
    "蘋果概念": [
        "蘋果", "Apple", "iPhone", "iPad", "MacBook", "AirPods",
        "Cupertino", "庫克", "Tim Cook",
    ],
    "車用電子": [
        "車用電子", "Automotive", "車載", "車規",
        "智慧座艙", "車內娛樂", "TPMS",
    ],
    "被動元件": [
        "被動元件", "MLCC", "積層陶瓷", "鋁質電容", "鉭質電容",
        "薄膜電阻", "電感器", "晶片電阻",
    ],
    # 註：移除 "電感/電阻/電容/Murata/國巨/華新科"（單字過於泛用、公司名易誤匹配
    # 為他人新聞中「順帶提到」的競爭對手）
    "Edge_AI": [
        "Edge AI", "邊緣運算", "On-device AI", "邊緣 AI",
        "終端 AI", "AIoT", "Edge Inference",
    ],
    "折疊螢幕": [
        "折疊螢幕", "Foldable", "Flexible Display", "可折疊",
        "鉸鏈", "Hinge", "折疊手機",
    ],
    "電動車_EV": [
        "電動車", "EV", "Tesla", "BYD", "Rivian",
        "電動載具", "純電", "插電式混合",
    ],
    "半導體設備": [
        "半導體設備", "蝕刻", "微影", "CMP", "EUV",
        "Lam", "AMAT", "ASML", "曝光機",
    ],
    "SiC功率元件": [
        "SiC", "碳化矽", "Silicon Carbide", "GaN", "氮化鎵", "功率元件",
        "Power Device", "MOSFET", "IGBT", "高壓 EV", "800V 平台",
        "寬能隙",
    ],
    "晶圓代工": [
        "晶圓代工", "晶圓廠", "Foundry", "晶圓投片", "晶圓良率",
        "先進製程", "成熟製程", "代工製程", "N3", "N2", "N5",
    ],
    # 註：刻意不收 "TSMC/台積電/聯電/世界先進/力積電" 等公司名 —
    # 這些代工廠在台股新聞中被「順帶提及」的頻率太高（任何 fabless / IDM
    # 客戶或供應商議題都會點到台積電），會把 IC 設計、封測、EMS 客戶等
    # 不相干公司誤判為「主導主題＝晶圓代工」。同理也把 "Fab" 移除，
    # 因為太短且常出現在 fabless / fab equipment 等非代工脈絡。
    "光學鏡頭": [
        "光學鏡頭", "鏡頭模組", "光學元件", "Lens", "Optical",
        "手機鏡頭", "玻璃鏡片",
    ],
}


def _kw_matches(kw: str, title: str) -> bool:
    is_short_ascii = len(kw) <= 5 and all(ord(c) < 128 for c in kw)
    if is_short_ascii:
        pattern = r"(?<![A-Za-z0-9])" + re.escape(kw) + r"(?![A-Za-z0-9])"
        return re.search(pattern, title, re.IGNORECASE) is not None
    return kw.lower() in title.lower()


def count_theme_mentions(news_titles: list[str], theme_keywords: dict = None) -> dict:
    """For a list of news titles, count how many titles mention each theme.
    A title is counted once per theme even if it has multiple keyword matches.
    Returns {theme_key: mention_count}."""
    if theme_keywords is None:
        theme_keywords = THEME_KEYWORDS
    counts = {k: 0 for k in theme_keywords}
    for title in news_titles:
        for theme_key, keywords in theme_keywords.items():
            if any(_kw_matches(kw, title) for kw in keywords):
                counts[theme_key] += 1
    return counts


def count_theme_mentions_detailed(news_titles: list[str], theme_keywords: dict = None) -> dict:
    """Like count_theme_mentions but also tracks which keywords matched per theme.
    Returns {theme_key: {"count": N, "kw_distinct": M, "kw_set": set}}.

    用途：detect_drift 可用 kw_distinct 過濾「12 條新聞但全是同一個關鍵字」這種
    虛假訊號 (通常是同一新聞被多家媒體轉發或同一事件重複報導)。"""
    if theme_keywords is None:
        theme_keywords = THEME_KEYWORDS
    out = {k: {"count": 0, "kw_set": set()} for k in theme_keywords}
    for title in news_titles:
        for theme_key, keywords in theme_keywords.items():
            matched_kws = [kw for kw in keywords if _kw_matches(kw, title)]
            if matched_kws:
                out[theme_key]["count"] += 1
                out[theme_key]["kw_set"].update(matched_kws)
    for k in out:
        out[k]["kw_distinct"] = len(out[k]["kw_set"])
        out[k]["kw_set"] = sorted(out[k]["kw_set"])  # Make JSON-friendly
    return out


if __name__ == "__main__":
    # Demo
    sample = [
        "AI伺服器 GB300 出貨大爆發 緯穎、廣達搶單",
        "貿聯-KY 受惠 NVLink 線材需求 Q1 營收年增 33%",
        "玻璃基板量產商機 TGV 概念股蓄勢待發",
    ]
    counts = count_theme_mentions(sample)
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        if v > 0:
            print(f"  {k}: {v}")
