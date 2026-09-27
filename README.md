# Rebalance · 개인 자산배분 운영

사용자가 지정한 날짜의 실제 종가로 보유수량과 CASH를 평가하고, 전략 규칙을 판정해 다음 거래일의 **수동 주문안**을 만드는 Streamlit 앱입니다. 실제 체결은 별도로 입력하며 기록은 Google Sheets에 보존합니다. 계좌 연동·자동 주문·외부 DB는 사용하지 않습니다.

사용자 수정 명세와 9월 25일 보완 검토를 반영했습니다. 후속 요청에 따라 Apps Script 양방향 저장을 추가했습니다. **Google Cloud 콘솔·서비스계정 설정은 필요하지 않지만, Apps Script 자체는 Google 관리형 Cloud 프로젝트를 사용합니다.**

## 사용 흐름

1. **설정 / 이번 달**에서 보유수량·현금을 불러오고 확인합니다. CASH는 원화 잔액을 수량에 입력하며 가격과 환율은 1입니다.
2. 평가 기준일을 선택하고 **지정일 종가 조회·판정**을 누릅니다. 종가 미확정·누락은 해당 계좌의 계산을 차단합니다.
3. **자산 현황 / 전략실**에서 분류·역할·계좌 현황, 조건 근거와 규칙을 확인합니다.
4. **주문안**의 수량·기존 현금·다음 거래일을 검토합니다. 수정하면 원안과 사유가 보존됩니다.
5. **기록**에서 체결 전 평가를 확정하고 **Sheets에 저장**합니다.
6. 거래 후 실제 체결일·수량·단가·환율·원화 금액을 입력합니다. 부분 체결·취소를 별도로 기록하고 변경한 원장을 다시 저장합니다.

주문안 생성·확정·다운로드는 보유수량을 바꾸지 않습니다. 새 세션에서는 Sheets에 저장한 Evaluations의 확정 주문안을 다시 열 수 있습니다. 저장하지 않은 작업은 전체 JSON 백업에 보관할 수 있습니다.

## 실행 및 배포

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Python 3.12를 권장합니다. Streamlit Community Cloud에서 저장소와 배포할 브랜치를 선택하고 Main file path를 `streamlit_app.py`로 설정합니다. 브라우저 테마를 기본으로 사용하며 Streamlit 메뉴에서 바꿀 수 있습니다.

- [Apps Script·Streamlit 연결 안내](docs/SHEETS_SETUP.md)
- [구현 범위·계산 규약·인수 검증](docs/FEATURE_SPEC.md)
- [9월 25일 보완 검토 및 기존 앱 격차표](docs/REVIEW_2026_09_25.md)

## 저장 모드

| 모드 | 읽기 | 저장 |
|---|---|---|
| Apps Script 연결 | 비밀번호 인증 후 세션 시작 시 1회 | 버튼으로 원장 저장, 중복·충돌 검사와 재조회 |
| 공개 Sheets 링크 | 읽기 버튼으로 미리보기 후 적용 | TSV 복사 또는 CSV를 사용자 시트에 직접 반영 |
| 비공개 파일 | 모든 표의 CSV·TSV·붙여넣기 | 전체 작업 JSON 백업 |

기본 6개 탭은 Holdings, Strategies, Snapshots, Actions, Cashflows, CategoryTargets입니다. Evaluations와 StrategyVersions를 추가해 당시 데이터·규칙·주문안을 보존합니다. Apps Script 저장은 이 8개 탭을 관리합니다. 파일과 공개 링크 입력도 계속 사용할 수 있습니다.

개인 보유내역·시크릿은 저장소에 넣지 않습니다. 기본 데이터는 보유수량이 0인 DEMO입니다. Apps Script 연결 시 APP_PASSWORD를 설정해야 원장을 읽습니다.

## 검증

```bash
python -m unittest discover -s tests -v
python -m compileall -q streamlit_app.py streamlit_app
```

Node.js가 있으면 Apps Script 원본의 저장·재시도·충돌·중간 실패 복구도 메모리 시트 어댑터로 검증합니다. GitHub Actions는 Python 3.12와 Node.js로 실행합니다.

고정 가격으로 계산과 Streamlit 화면을 검증했습니다. 실제 Yahoo 요청은 이 개발 환경에서 요청 제한·시간 초과가 발생했습니다. 사용자 Apps Script URL·시크릿·7개 실제 전략은 제공되지 않아 실제 Sheets 왕복·해당 전략 검증·운영 배포 확인은 남아 있습니다. 원격 검증 브라우저의 localhost 접근도 제한되어 시각 검증은 완료하지 못했습니다.
