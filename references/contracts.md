# 저장 계약 — v2

현재 상태는 두 종류의 JSON으로 관리한다. 컷·단계·수정 버전마다 JSON 파일을 추가하지 않는다.

```text
outputs/<series-id>/
  series.json
  assets/                      # 캐릭터 시트·원본 등 실제 파일
  episodes/<episode-id>/
    episode.json
    history.jsonl
    art/                       # 생성 이미지
    renders/                   # 1920·1080 PNG
    exports/<revision>/        # 승인 출력 PNG
```

## series.json

`schema_version: 2`, `series_id`, 정수 `revision`, `title`, `episode_ids`, `style`, `characters`, 공통 식자·표시 설정을 담는다. style과 characters에는 표현 규칙, 출처, 이미지 artifact, QA, 실제 사용자 승인 기록을 직접 넣는다. 스타일과 캐릭터는 별개 객체로 유지한다. 각각의 JSON 파일은 만들지 않는다. 확정 시 변경된 설정은 `save_series`로 저장하고, 에피소드는 사용한 설정을 documents 안에 고정해 나중에 시리즈 설정이 달라져도 영향을 받지 않게 한다.

## episode.json

`schema_version: 2`, `series_id`, `episode_id`, `current_revision`, `phase`, `status`, `next_action`과 아래 정보를 담는다.

| 필드 | 내용 |
| --- | --- |
| documents.brief | 주제·타깃·톤·분량·결말 |
| documents.storyboard | style_ref와 character_refs에 사용 설정 객체, panels에 컷별 사건·표정·구도·대사 |
| generation_provenance | 프롬프트·도구·입력 이미지·생성 결과·원본 크기·변환 이력 |
| ordered_panels | panel_id, order, 1920·1080 이미지 artifact, 인라인 render_report |
| render_report.layout | 좌표·폰트·줄바꿈·보호 영역·표시 설정 |
| final_qa | decision, target_revision, outputs_hash, observations, issues |
| approvals | 실제 응답, 대상 revision, 승인 당시 content_hash |
| exports | 승인 출력 순서·이미지 경로·해시·승인 ID |
| runs / panel_states | 재시도 횟수와 단계별 작업 상태 |

별도 brief, storyboard, layout, render-report, generation, QA, export-manifest 파일을 만들지 않는다. 반환된 결과 객체를 이 문서에 넣는다. final_qa는 출력 목록을 복제하지 않고 `fingerprint(ordered_panels)`를 outputs_hash에 저장한다.

컷에는 panel_id, order, purpose, characters, action, expression, composition, background, texts를 둔다. background.mode는 none/minimal/detailed. 텍스트는 text_id, kind(dialogue/narration/sfx), speaker_id, text, reading_order를 갖는다. 무대사는 빈 texts. 문서 내부 콘티의 schema_version은 기존 검증기와 호환되는 1이다.

이미지 artifact는 path·sha256·role과 선택적인 width·height를 담는다. path는 Workspace 루트 기준이며 해시는 실제 바이트 기준이다. 이미지 원본과 최종본은 별도 PNG로 보존한다. 변경된 이미지는 새 경로에 저장해 과거 이력의 이미지 참조를 덮어쓰지 않는다.

## history.jsonl

에피소드별 파일 하나에 save/approve/export/migrate 변경 이벤트를 누적한다. 이벤트에는 순서, 시각, 변경된 최상위 필드(set/remove), 전후 체크섬이 있다. 폴더별 전체 snapshot은 생성하지 않는다. 처음 이벤트만 현재 전체 정보를 담고 이후 이벤트는 변경 필드만 기록한다. 현재 정보와 이력이 서로 다르면 오류로 처리한다. 저널 기록 후 episode.json 교체 전 중단되면 다음 load에서 복구한다. 에이전트가 직접 JSON을 수정하지 말고 tool을 사용한다.

생성 성공과 QA는 승인과 다르다. 새 revision에는 이전 승인 이력이 남지만 새 결과에 적용되지 않는다. 승인과 출력은 콘텐츠 해시를 검사한다. 중요한 확정 시점의 기록도 approve/export 이벤트로 재구성할 수 있다.

## 기존 데이터

v1은 읽기·이전용 legacy_state에만 남긴다. migrate_project로 활성 메타데이터를 통합하고 미디어를 해시로 중복 제거해 복사한다. 기존 데이터는 수정하지 않는다. 이전 승인 증거는 migration 기록에 남긴다. 이미지는 바이트가 동일한지 검증한다. 이전 JSON은 보관용 압축 파일로 유지하며 평소에는 새 두 JSON만 읽는다.
