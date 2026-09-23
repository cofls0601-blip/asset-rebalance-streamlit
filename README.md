# 월말 자산배분 도우미

Google Cloud나 별도 데이터베이스 없이 사용하는 독립형 Streamlit 자산배분 앱입니다.
공개 Google Sheets를 읽기 전용으로 불러오고, 월말 결과는 TSV/CSV로 만들어 사용자가
직접 자신의 시트에 붙여넣습니다. 자동 주문 기능은 포함하지 않습니다.

## 주요 기능

- 전략별 현재 비중, 목표 비중, 괴리와 상태색 대시보드
- 정적 비중, SMA 필터, 모멘텀, 낙폭 매수, 낙폭 비중전환, 장기보유 규칙
- SMA·모멘텀·낙폭·현재가를 조합하는 노코드 조건 규칙
- 문헌 자산배분 전략 템플릿 19종과 한국 상장 ETF 근사 변환
- 실제 체결수량·체결금액을 반영한 다음 달 보유내역 생성
- 월별 스냅샷, 자산군 히스토리, 성과 및 벤치마크 비교
- 전략 버전, 적용일, 변경 이유와 참고 문헌 기록
- Google Sheets용 TSV 복사 및 CSV 다운로드
- Rebalance Terminal 다크 UI

## 로컬 실행

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Streamlit Community Cloud 배포

1. Streamlit Community Cloud에서 이 저장소를 선택합니다.
2. 브랜치는 `main`, Main file path는 `streamlit_app.py`로 지정합니다.
3. 별도 Secrets 없이 배포합니다.

## Google Sheets 탭

| 탭 | 용도 |
|---|---|
| `Holdings` | 전략·계좌·종목·목표비중·보유수량 |
| `Strategies` | 전략 규칙·파라미터·버전·문헌 |
| `Snapshots` | 월말 평가액과 당시 전략 버전 |
| `Actions` | 계획과 실제 체결 기록 |
| `Cashflows` | 입출금 원장 |
| `CategoryTargets` | 자산군 목표비중 |

시트 공유 설정은 **링크가 있는 모든 사용자: 뷰어**로 설정합니다. 비공개 시트는 표를
직접 복사해 앱 입력창에 붙여넣을 수 있습니다.

## 테스트

```bash
python -m unittest discover -s tests -v
```

현재 회귀 테스트는 전략 계산, 현금 처리, 가격 검증, 체결 반영, 전략 템플릿과 버전
기록을 포함합니다.
