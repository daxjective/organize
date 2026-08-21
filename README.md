# Automation

파일 정리 자동화 도구 `organize`.

여러 정리 작업(압축 해제 · 중복 제거 · 종류별 분류 · 날짜별 분류)을 골라 순서대로 엮어 실행한다.
자주 쓰는 조합은 이름을 붙여 저장한다.

## 새 PC 에서 시작하기

이 저장소는 **특정 PC 를 전제하지 않는다.** 클론한 뒤 아래 순서면 동작한다.

```
git clone <이 저장소>
cd Automation

python -m organize doctor          환경 점검. 부족한 것을 알려준다
python -m organize preview 바탕화면  미리보기 (파일을 건드리지 않는다)
python -m organize run 바탕화면 --apply   실제 실행
python -m organize undo            방금 실행을 되돌린다
```

필요한 것은 **Python 3.11 이상**뿐이다. 외부 패키지는 없다.
(`Pillow` 가 있으면 사진의 촬영일을 읽는다. 없어도 파일명·수정시각으로 동작한다.)

`config.local.json`(이 PC 의 폴더 위치)은 저장소에 포함되지 않는다.
없어도 동작하며, 백업 드라이브 같은 위치를 추가하고 싶을 때만 지정한다.

## 문서

- 설계: [`docs/superpowers/specs/2026-08-19-organize-design.md`](docs/superpowers/specs/2026-08-19-organize-design.md)
- 이전 스크립트: [`legacy/`](legacy/) — **실행하지 말 것.** 옛 PC 경로가 하드코딩되어 있다

## 현재 상태

**만드는 중이다. 아직 실행되지 않는다.**

엔진은 대부분 만들어졌고 테스트로 지켜지고 있지만, 이것들을 하나로 엮는
러너와 CLI 가 아직 없다. 지금 `python -m organize doctor` 를 치면
"아직 없는 명령입니다" 가 뜬다.

| 부분 | 상태 |
|---|---|
| 폴더 훑기 · 날짜 판정 · 중복 판정 | 됨 |
| 분류 규칙(프로파일) 읽기 | 됨 |
| 압축 풀기 · 중복 치우기 · 종류별 분류 · 날짜별 분류 | 됨 |
| 실제 파일 이동 | 됨 |
| 위 작업들을 엮는 러너 · 실행기 · 되돌리기 | **아직** |
| CLI · 레시피 | **아직** |
| GUI | 다음 계획 |

만들어진 부분이 실제로 도는지는 이렇게 확인한다:

```
python3 -m pytest -q
```

계획과 진행 상황: [`docs/superpowers/plans/`](docs/superpowers/plans/)
