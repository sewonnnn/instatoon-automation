# 로컬 Tool — v2

Python 3.11+, Pillow, fontTools를 사용한다. 실행은 `python -m tools.instatoon COMMAND --request -`에 JSON을 표준입력으로 전달한다. `--root`는 작업 루트이며 모든 artifact 경로는 이 루트 기준이다. 출력은 그 아래 outputs에 저장한다. 요청 파일을 별도로 생성할 필요가 없다.

## 상태 저장

- `save_series`: `{series_id, expected_revision, series}`. 최초 expected_revision은 null, 이후 정수 revision. 스타일·캐릭터·공통 설정을 series 객체에 넣는다. episode_ids도 명시적으로 관리한다.
- `save_revision`: `{series_id, episode_id, expected_revision, state, documents}`. 최초 expected_revision은 null, 이후 r001 등. state와 documents는 현재 전체 정보다. documents는 brief와 storyboard를 인라인으로 담는다. 반환값은 state. 에피소드 파일과 history.jsonl만 갱신한다.
- `load_project`: `{series_id, episode_id}`. 현재 상태와 파일 해시 문제를 반환한다. 기록 도중 중단된 저장은 저널로 복구한다.
- `validate_episode`: 같은 ID와 선택적인 `stage: "final"`. 반환 decision을 확인한다. 명령 status=ok와 QA pass는 다르다.

state에 approvals, exports, snapshot, current_revision, event_seq를 직접 전달하지 않는다. 이전 runs ID와 재시도 횟수는 보존한다. 직접 JSON을 편집하면 기록과 다르므로 검증에 실패한다. 이미지 변경도 해시로 감지한다.

## 그림과 식자

검색·이미지 생성은 세션에서 실제 사용 가능한 도구를 사용한다. 가짜 실행 기록을 만들지 않는다. 생성 프롬프트·입력·결과·QA는 episode의 generation_provenance와 panel_states 등에 저장한다.

`render_panel` 입력은 panel, art(artifact), layout, output_dir다. 원본은 정사각형이며 1920·1080 PNG를 만든다. 레이아웃·보고서는 파일이 아닌 반환값 `report`로 제공한다. `ordered_panels` 원소는 다음과 같이 구성한다.

```python
rendered = render_panel(ws, request)
entry = {"panel_id": panel["panel_id"], "order": panel["order"],
         **rendered["report"]["outputs"], "render_report": rendered["report"]}
```

layout은 schema_version=1, panel_id, canvas(width=1920,height=1920), items, protected_regions, disclosure를 갖는다. item에는 text_id, reading_order, box(x,y,width,height), font_path, font_index, font_size, line_height, padding, tail을 둔다. lines를 지정하면 원문 보존을 검사하고 생략하면 실제 글자 폭으로 줄바꿈한다. container=none이면 말풍선 배경·테두리·꼬리 없이 글자만 합성한다. 폰트는 실제 한글 폰트 경로를 쓴다. 넘침·누락 글리프·보호 영역 충돌은 실패다.

표시는 `disclosure: {"enabled": false}`로 끌 수 있다. 켜면 text, box, font_path, font_size 등이 필요하다. 모난이 시리즈는 사용자 요청으로 표시를 끈다. 생성 출처 기록은 유지한다.

`metadata_files: true`는 v1 호환 검증에만 사용하며 신규 제작에는 쓰지 않는다.

`build_preview`: `{panels: [{panel_id, order, image}], output_dir}`. preview.png 하나와 입력 목록 객체를 반환한다. panels.json은 생성하지 않는다.

## 최종 QA·승인·출력

최종 QA는 실제 이미지 검토 후 episode.state.final_qa에 넣는다.

```python
from tools.instatoon.state import fingerprint
qa = {"target_revision": "r002", "decision": "pass",
      "outputs_hash": fingerprint(ordered_panels), "issues": []}
```

phase=final_review로 저장하고 validate_episode(stage=final)를 실행한다. 콘티와 보고서, 출력 크기·해시·순서와 QA 대상이 일치해야 한다.

실제 사용자 승인 후 `record_approval`에 series_id, episode_id, stage(storyboard/final), target_revision, user_response를 전달한다. `export_episode`에는 ID와 target_revision을 전달한다. 승인된 PNG를 exports/<revision>/1080 및 1920으로 복사하고 manifest는 episode.exports에 인라인 저장한다. 별도 manifest.json은 생성하지 않는다. 같은 승인으로 재실행하면 검증 후 기존 출력을 반환한다.

## 이전 데이터 변환

`migrate_project`: `{source_root, series_id, episode_id}`. source_root의 v1 outputs를 읽고 현재 작업 루트의 새로운 outputs/<series_id>로 통합한다. 대상 series/episode가 이미 있으면 중단한다. 원본 경로·해시 검증과 활성 미디어 복사를 수행한다. v1 JSON·PNG는 보관하며 자동 삭제하지 않는다. 최종 승인 기록은 기존 승인과 동일한 이미지 바이트에만 연결한다. 이동 후 반환 validation과 실제 최종 검증을 확인한다.

## 검증

`python -m pytest -q`로 v1 호환성과 v2 저장·동시 저장·중단 복구·변조 감지·식자·승인·출력을 확인한다. `python -m examples.render_demo --font /System/Library/Fonts/AppleSDGothicNeo.ttc`는 도형 기반 식자 예시다. 실제 사용자 승인은 기록하지 않는다.
