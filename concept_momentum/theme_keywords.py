#!/usr/bin/env python3
"""
概念主題的關鍵字字典：用於從新聞標題中匹配各概念。

每個概念列出多個關鍵字（中英混合），匹配「至少一個」即視為提及該概念。
關鍵字應該是該概念的標誌性詞彙，避免過度泛用導致誤判。
"""

THEME_KEYWORDS = {
    "CPO_矽光子": [
        "CPO", "矽光子", "Co-Packaged", "光通訊", "光收發", "光模組",
        "三五族", "InP", "矽光", "光晶片",
    ],
    "AI伺服器": [
        "AI伺服器", "AI Server", "GB200", "GB300", "Blackwell", "Hopper",
        "輝達伺服器", "資料中心", "AI 機架", "DGX", "HGX", "Foxconn AI",
        "NVL", "AI 主板",
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
        "台電", "GIS", "高壓電",
    ],
    "軍工": [
        "軍工", "國防", "Defense", "軍用", "戰機", "導彈", "雷達",
        "潛艦", "海巡", "F-16", "天弓",
    ],
    "機器人": [
        "機器人", "Robot", "Humanoid", "人形機器人", "Optimus",
        "工業機器人", "服務型機器人", "Tesla 機器人", "雙足機器人",
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
        "太陽能", "Solar", "光電", "PV", "矽晶圓",
        "綠能", "再生能源",
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
        "被動元件", "MLCC", "電感", "電阻", "電容",
        "Murata", "國巨", "華新科",
    ],
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
    "光學鏡頭": [
        "光學鏡頭", "鏡頭模組", "光學元件", "Lens", "Optical",
        "手機鏡頭", "玻璃鏡片",
    ],
}


def count_theme_mentions(news_titles: list[str], theme_keywords: dict = None) -> dict:
    """For a list of news titles, count how many titles mention each theme.
    A title is counted once per theme even if it has multiple keyword matches.
    Returns {theme_key: mention_count}."""
    if theme_keywords is None:
        theme_keywords = THEME_KEYWORDS
    counts = {k: 0 for k in theme_keywords}
    for title in news_titles:
        for theme_key, keywords in theme_keywords.items():
            if any(kw.lower() in title.lower() for kw in keywords):
                counts[theme_key] += 1
    return counts


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
