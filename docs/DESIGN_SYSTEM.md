# Rebalance 디자인 시스템

모든 스타일은 `streamlit_app/theme.css` 하나에 있습니다. 맨 위 `:root` 토큰만 바꾸면 전 화면이 따라갑니다.
차트·표 색처럼 Python에서 써야 하는 값은 `streamlit_app/ui.py`의 `TOKENS`에 같은 값으로 두고, `tests/test_design_tokens.py`가 두 곳이 어긋나면 실패합니다.

## 색상
| 토큰 | 값 | 용도 |
|---|---|---|
| `--bg` | #f5f2ee | 페이지 배경 |
| `--surface` | #fffdfa | 카드·표·버튼 |
| `--surface-sunk` | #efe9e1 | 세그먼트 트랙 |
| `--field` | #ffffff | 입력칸 |
| `--ink` / `--muted` / `--subtle` | #292d2a / #827d76 / #a39d94 | 본문 / 보조 / 흐림 |
| `--line` / `--line-strong` | #e8dfd5 / #d9cdbf | 테두리 |
| `--accent` (+`-strong`, `-soft`) | #b95e3d | 주 버튼·선택·포커스 |
| `--deep` | #263d33 | 총자산 카드·규칙 미리보기 |
| `--sage` | #477665 | 완료 단계 |
| `--under` (+`-soft`, `-line`) | #276893 | 목표 미달 · 매수 |
| `--met` (+`-soft`, `-line`) | #387762 | 충족 · 보유 유지 · THEN |
| `--over` (+`-soft`, `-line`) | #ad5146 | 초과 · 매도 · ELSE · 차단 |
| `--wait` (+`-soft`) | #72695f | 일정 대기 |

의미 색은 화면마다 같은 뜻으로만 씁니다: 파랑 = 더 사야 함, 초록 = 괜찮음, 빨강 = 줄여야 함/문제.

## 타이포·간격·모서리
- 글꼴 `--font` (Pretendard 우선), 숫자는 항상 고정폭(tabular).
- 크기 `--fs-2xs .7` · `xs .76` · `sm .84` · `md .92` · `lg 1.05` · `xl 1.3` · `2xl 1.9` rem.
- 굵기 `--fw-medium 600` · `semibold 680` · `bold 760` · `heavy 800`.
- 간격 `--sp-1..6` = 4 · 8 · 12 · 16 · 20 · 24px.
- 모서리 `--r-sm 10` · `md 12` · `lg 14` · `xl 16` · `pill`.
- 그림자 `--shadow-1`(선택된 세그먼트) · `--shadow-2`(모바일 상단 바) · `--shadow-accent`(주 버튼). 포커스는 `--focus-ring`.
- 터치 `--tap 44px`, 모바일 버튼 `--tap-lg 50px`.

## 컴포넌트 클래스
| 클래스 | 화면 |
|---|---|
| `.target-chip.{under,met,over}`, `.decision-badge.{order,hold,wait}` | 상태 배지 (같은 모양) |
| `.monthly-summary` · `.summary-hero` · `.summary-mini` | 이번 달 요약 |
| `.order-list` · `.order-row` · `.order-side.{buy,sell}` | 주문안 |
| `.asset-card.status-{under,met,over}` | 자산 현황 카드 |
| `.rule-preview` (+`.signal .number .pass .fail`) | 전략실 규칙 문장 |
| `.workflow-bar.{is-done,is-active}` | 진행 단계 |

## 모바일 (≤ 800px)
사이드바 대신 상단 바(`mobile_toolbar`), 데스크톱 표 대신 카드(`mobile_*` 키 컨테이너).
입력칸은 흰 상자 + 16px 글자(iOS 확대 방지), 버튼은 전체 폭 50px.
같은 미디어 쿼리를 여러 개 만들지 말고 파일 아래쪽 한 블록에 추가하세요.

## 규칙
- 새 색을 직접 쓰지 말고 토큰을 추가한 뒤 참조하세요.
- `--warm-*`, `--terracotta*`, `--deep-green` 은 이전 이름입니다. 동작은 하지만 새 코드에서는 새 이름을 쓰세요.
