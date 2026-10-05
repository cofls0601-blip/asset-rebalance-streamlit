모바일 UI 개선 (기준: main a39255e)

바뀐 파일 2개 - 저장소의 같은 위치에 덮어쓰세요.
  streamlit_app.py           차트 색상/여백 테마만 변경 (계산 로직 변경 없음)
  streamlit_app/theme.css    모바일(800px 이하) 스타일

또는 git 으로 커밋째 적용:
  git am patches/*.patch

커밋
  1) 모바일 입력칸·버튼·상단 바를 미리보기 디자인에 맞게 정리
  2) 모바일 드롭다운 테두리·주문 필터 칩·차트 테마 정리

검증: python -m unittest discover -s tests  -> 95 tests OK
