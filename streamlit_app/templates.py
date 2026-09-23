from __future__ import annotations

import json
from copy import deepcopy

import pandas as pd


KR_SUBSTITUTES = {
    "SPY": ("360750", "TIGER 미국S&P500"), "VTI": ("360750", "TIGER 미국S&P500"),
    "QQQ": ("133690", "TIGER 미국나스닥100"), "EFA": ("251350", "KODEX 선진국MSCI World"),
    "VEU": ("251350", "KODEX 선진국MSCI World"), "VXUS": ("251350", "KODEX 선진국MSCI World"),
    "EEM": ("195930", "TIGER 신흥국MSCI"), "TLT": ("305080", "TIGER 미국채10년선물"),
    "IEF": ("152380", "KODEX 국채선물10년"), "SHY": ("153130", "KODEX 단기채권"),
    "BND": ("153130", "KODEX 단기채권"), "TIP": ("153130", "KODEX 단기채권"),
    "VNQ": ("329200", "TIGER 리츠부동산인프라"), "GLD": ("132030", "KODEX 골드선물(H)"),
}


def _asset(ticker, name, category, target, role):
    return {"ticker": ticker, "name": name, "market": "KR" if ticker == "CASH" else "US",
            "category": category, "target_pct": target, "role": role}


def _cash(target=0, role="대기현금"):
    return _asset("CASH", "현금", "현금", target, role)


def _template(id_, name, kind, family, rule, description, source, rebalance, trait, assets, params=None):
    return {"id": id_, "name": name, "kind": kind, "family": family, "rule": rule,
            "description": description, "source": source, "rebalance": rebalance, "trait": trait,
            "assets": assets, "params": params or {}}


A = _asset
TEMPLATES = [
    _template("all-weather", "올웨더 (All Weather)", "정적", "고정비중 · 리스크 패리티", "static",
              "경기와 물가의 네 국면에 대응하도록 주식·채권·금·원자재를 배분합니다.", "Ray Dalio / Bridgewater (1996)",
              "연 1회 또는 괴리 ±5%p", "채권 비중이 높고 방어적", [A("SPY","SPDR S&P 500","선진국 주식",30,"성장"),A("TLT","미국 장기채","선진국 채권",40,"침체 방어"),A("IEF","미국 중기채","선진국 채권",15,"침체 방어"),A("GLD","금","금",7.5,"물가 상승"),A("DBC","원자재","기타",7.5,"물가 상승")]),
    _template("permanent", "영구 포트폴리오 (Permanent)", "정적", "고정비중 · 4분면 균등", "static",
              "주식·장기채·금·현금을 각각 25% 보유합니다.", "Harry Browne (1981), Fail-Safe Investing", "연 1회 또는 15~35% 밴드", "구매력 보존 중심",
              [A("SPY","SPDR S&P 500","선진국 주식",25,"번영"),A("TLT","미국 장기채","선진국 채권",25,"디플레이션"),A("GLD","금","금",25,"인플레이션"),_cash(25)]),
    _template("golden-butterfly", "골든 버터플라이 (Golden Butterfly)", "정적", "영구 포트폴리오 변형", "static",
              "영구 포트폴리오에 미국 소형가치주를 더한 5자산 균등 구성입니다.", "PortfolioCharts / Tyler", "연 1회", "주식 40%, 방어 60%",
              [A("VTI","미국 전체 주식","선진국 주식",20,"대형"),A("IWN","미국 소형가치","선진국 주식",20,"소형가치"),A("TLT","미국 장기채","선진국 채권",20,"장기채"),A("SHY","미국 단기채","선진국 채권",20,"단기채"),A("GLD","금","금",20,"금")]),
    _template("classic-6040", "클래식 60/40", "정적", "전통적 균형", "static", "주식 60%와 채권 40%의 기준선입니다.", "전통적 균형 펀드", "분기 또는 연 1회", "기준 포트폴리오", [A("VTI","미국 전체 주식","선진국 주식",60,"성장"),A("BND","미국 종합채권","선진국 채권",40,"방어")]),
    _template("three-fund", "3-펀드 포트폴리오 (Bogleheads)", "정적", "단순 글로벌 분산", "static", "미국·미국 외 주식과 채권 세 자산으로 구성합니다.", "John C. Bogle / Bogleheads", "연 1회", "단순하고 낮은 비용", [A("VTI","미국 전체 주식","선진국 주식",45,"미국"),A("VXUS","미국 외 주식","선진국 주식",30,"해외"),A("BND","미국 종합채권","선진국 채권",25,"채권")]),
    _template("swensen", "예일 모델 (Swensen)", "정적", "기관형 · 대안자산", "static", "주식·리츠·명목채·물가연동채를 넓게 분산합니다.", "David Swensen, Unconventional Success", "연 1회", "장기 성장형", [A("VTI","미국 전체 주식","선진국 주식",30,"미국"),A("EFA","선진국 주식","선진국 주식",15,"해외"),A("EEM","신흥국 주식","신흥국 주식",5,"신흥국"),A("VNQ","미국 리츠","기타",20,"부동산"),A("TLT","미국 장기채","선진국 채권",15,"장기채"),A("TIP","물가연동채","선진국 채권",15,"물가연동")]),
    _template("ivy", "아이비 포트폴리오 (Ivy)", "정적", "5자산 균등", "static", "주식·채권·원자재·리츠에 균등 배분합니다.", "Meb Faber (2009), The Ivy Portfolio", "분기 또는 연 1회", "실물자산 포함", [A("VTI","미국 전체 주식","선진국 주식",20,"미국"),A("VEU","미국 외 주식","선진국 주식",20,"해외"),A("BND","미국 종합채권","선진국 채권",20,"채권"),A("DBC","원자재","기타",20,"원자재"),A("VNQ","미국 리츠","기타",20,"리츠")]),
    _template("no-brainer", "노브레이너 (Bernstein)", "정적", "4분할", "static", "미국 대형·소형, 해외주식, 단기채를 균등 보유합니다.", "William Bernstein", "연 1회", "주식 75%", [A("SPY","미국 대형주","선진국 주식",25,"대형"),A("IWM","미국 소형주","선진국 주식",25,"소형"),A("EFA","선진국 주식","선진국 주식",25,"해외"),A("SHY","미국 단기채","선진국 채권",25,"단기채")]),
    _template("coffeehouse", "커피하우스 (Coffeehouse)", "정적", "60/40 + 금", "static", "주식 60%, 채권 30%, 금 10% 구성입니다.", "Bill Schultheis, The Coffeehouse Investor", "연 1회", "금으로 위기 완충", [A("VTI","미국 전체 주식","선진국 주식",30,"미국"),A("VXUS","미국 외 주식","선진국 주식",30,"해외"),A("BND","미국 종합채권","선진국 채권",30,"채권"),A("GLD","금","금",10,"금")]),
    _template("risk-parity-4", "간이 리스크 패리티 (4자산)", "정적", "위험 균등 근사", "static", "주식·장기채·금·현금을 같은 비중으로 나눕니다.", "Risk Parity 계열 단순 근사", "분기 또는 연 1회", "낮은 변동성 지향", [A("SPY","미국 주식","선진국 주식",25,"주식"),A("TLT","미국 장기채","선진국 채권",25,"장기채"),A("GLD","금","금",25,"금"),_cash(25)]),
]


def _dynamic(id_, name, family, source, assets, rule="momentum_rotate", params=None, description="월말 추세와 모멘텀으로 보유 자산을 선택합니다."):
    return _template(id_, name, "동적", family, rule, description, source, "월 1회 판정", "신호에 따라 위험 노출 변경", assets, params)


TEMPLATES += [
    _dynamic("gtaa-faber", "Faber GTAA (10개월 SMA)", "추세추종", "Meb Faber (2007)", [A("VTI","미국 주식","선진국 주식",20,"필터"),A("VEU","해외 주식","선진국 주식",20,"필터"),A("BND","미국 채권","선진국 채권",20,"필터"),A("DBC","원자재","기타",20,"필터"),A("VNQ","미국 리츠","기타",20,"필터"),_cash()], "sma_filter_rebalance", {"sma_tickers":["VTI","VEU","BND","DBC","VNQ"],"sma_months":10,"quarter_end_restore":False}),
    _dynamic("laa", "LAA (Lazy Asset Allocation)", "Keller TAA", "Keller & Keuning (2016)", [A("QQQ","나스닥100","선진국 주식",12.5,"필터"),A("EFA","선진국 주식","선진국 주식",12.5,"필터"),A("SPY","S&P 500","선진국 주식",25,"주식"),A("IEF","미국 중기채","선진국 채권",25,"채권"),A("GLD","금","금",25,"금"),_cash()], "sma_filter_rebalance", {"sma_tickers":["QQQ","EFA"],"sma_months":10,"quarter_end_restore":True}),
    _dynamic("gem", "GEM (Global Equities Momentum)", "듀얼 모멘텀", "Gary Antonacci (2014)", [A("SPY","미국 주식","선진국 주식",0,"후보"),A("EFA","해외 주식","선진국 주식",0,"후보"),_cash(100)], params={"winner_share":1,"cash_winner_share":0,"cash_no_winner":1}),
]

for id_, name, family, source, tickers in [
    ("vaa-g4","VAA-G4 (Vigilant Asset Allocation)","Keller TAA · 카나리아","Keller & Keuning (2017)",["SPY","EFA","EEM","IEF","SHY"]),
    ("daa-g12","DAA-G12 (Defensive Asset Allocation)","Keller TAA · 방어 로테이션","Keller & Keuning (2017)",["SPY","EFA","EEM","IEF","TLT","SHY","GLD"]),
    ("paa-g12","PAA-G12 (Protective Asset Allocation)","Keller TAA · 단계적 위험축소","Keller & Keuning (2016)",["SPY","EFA","EEM","IEF"]),
    ("baa-g12","BAA-G12 (Bold Asset Allocation)","Keller TAA · 공격형","Keller & van Putten (2022)",["QQQ","SPY","EEM","IEF","TLT"]),
    ("haa","HAA (Hybrid Asset Allocation)","Keller TAA · 하이브리드","Keller & Keuning (2018)",["SPY","QQQ","EFA","IEF"]),
    ("dga","DGA (Dividend & Growth Allocation)","배당+성장 모멘텀","Keller 계열 변형",["SPY","QQQ","SCHD","VNQ","IEF"]),
]:
    cats = {"EEM":"신흥국 주식","IEF":"선진국 채권","TLT":"선진국 채권","SHY":"선진국 채권","GLD":"금","VNQ":"기타"}
    TEMPLATES.append(_dynamic(id_, name, family, source, [A(t,t,cats.get(t,"선진국 주식"),0,"후보") for t in tickers]+[_cash(100)], params={"winner_share":1,"cash_winner_share":0,"cash_no_winner":1}))


def template_by_id(template_id: str) -> dict:
    return deepcopy(next(item for item in TEMPLATES if item["id"] == template_id))


def apply_template(template_id: str, code: str, account: str, use_kr_substitutes: bool = False) -> tuple[dict, pd.DataFrame]:
    template = template_by_id(template_id)
    assets = []
    ticker_map = {}
    for item in template["assets"]:
        asset = deepcopy(item)
        original = asset["ticker"]
        if use_kr_substitutes and original in KR_SUBSTITUTES:
            asset["ticker"], asset["name"] = KR_SUBSTITUTES[original]
            asset["market"] = "KR"
            ticker_map[original] = asset["ticker"]
        assets.append({"strategy": code, "account": account, **asset, "shares": 0.0})
    params = deepcopy(template["params"])
    if "sma_tickers" in params:
        params["sma_tickers"] = [ticker_map.get(t, t) for t in params["sma_tickers"]]
    strategy = {"code": code, "account": account, "description": template["description"],
                "dynamic": template["kind"] == "동적", "active": True, "annual_limit": 0.0,
                "rule": template["rule"], "params_json": json.dumps(params, ensure_ascii=False),
                "version": "1.0", "effective_date": "", "source": template["source"], "change_note": "템플릿에서 생성"}
    return strategy, pd.DataFrame(assets)
