디자인 시스템 개선 (기준 커밋: 645964e = 현재 main)

방법 A) 파일을 저장소 같은 위치에 덮어쓰기 / 추가하기
  streamlit_app.py              차트 설정을 ui.py 토큰에서 가져옴
  streamlit_app/theme.css       토큰 기반으로 재정리 (모바일 블록 1개로 통합)
  streamlit_app/ui.py           TOKENS / CHART_* 추가
  docs/DESIGN_SYSTEM.md         (신규) 토큰·컴포넌트 문서
  tests/test_design_tokens.py   (신규) CSS↔Python 토큰 동기화 테스트

방법 B) git am patches/*.patch

검증: python -m unittest discover -s tests -> 110 tests OK
