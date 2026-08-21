# Automation

파일 정리 자동화 도구 `organize`.

여러 정리 작업(압축 해제 · 중복 제거 · 종류별 분류 · 날짜별 분류)을 골라 순서대로 엮어 실행한다.
자주 쓰는 조합은 이름을 붙여 저장한다.

## 새 PC 에서 시작하기

이 저장소는 **특정 PC 를 전제하지 않는다.** 클론한 뒤 아래 순서면 동작한다.

```
git clone <이 저장소>
cd Automation

python -m organize doctor     환경 점검. 부족한 것을 알려준다
python -m organize gui        첫 실행 화면이 폴더 위치를 자동 감지한다
```

필요한 것은 **Python 3.11 이상**뿐이다. 외부 패키지는 없다.

`config.local.json`(이 PC 의 폴더 위치)은 저장소에 포함되지 않는다.
없어도 동작하며, 백업 드라이브 같은 위치를 추가하고 싶을 때만 설정 화면에서 지정한다.

## 문서

- 설계: [`docs/superpowers/specs/2026-08-19-organize-design.md`](docs/superpowers/specs/2026-08-19-organize-design.md)
- 이전 스크립트: [`legacy/`](legacy/) — **실행하지 말 것.** 옛 PC 경로가 하드코딩되어 있다

## 현재 상태

설계 완료, 구현 전.
