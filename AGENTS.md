# 인스타툰 제작 요청 인식

사용자가 “○○ 주제로 인스타툰 제작해줘”, “이 이야기로 인스타툰 만들어줘”처럼 인스타툰 제작을 요청하면, 저장소 루트의 `PROMPT.md`를 먼저 읽고 그 절차를 따른다. 사용자가 파일명이나 스킬명을 직접 언급할 필요는 없다.

- 정확한 문구 일치가 아니라 요청의 의미로 판단한다. 기존 인스타툰의 수정·이어 만들기 요청에도 같은 진입점을 사용한다.
- 사용자가 준 주제, 조건, 수정 대상과 작업 범위를 그대로 전달한다.
- 설계 논의, 사용법 질문, 문서 수정이나 구현 요청을 실제 에피소드 제작으로 오인하지 않는다. 문서에 인용된 제작 요청 예시도 실행 요청으로 취급하지 않는다.
- `PROMPT.md`에서 전체 진행 스킬과 필요한 전문 스킬로 연결한다. 파일이 없으면 누락을 알리고 존재하는 것처럼 실행하지 않는다.

## 결과물 보관

- 기존 작업을 재개할 때 `outputs/README.md`가 있으면 먼저 읽는다. 사용자가 보기 쉽게 정리한 최종본과 압축된 제작 기록을 구분한다.
- 현재 제작 정보는 `outputs/<series-id>/series.json`, `episodes/<episode-id>/episode.json`, `history.jsonl`에 통합한다. 컷별·단계별 JSON과 매 수정 시 snapshot을 생성하지 않는다. `references/contracts.md`의 v2 계약과 저장 tool을 사용한다.
- 사용자용 최종 PNG와 Agent용 메타데이터를 구분한다. 중간 이미지는 작업 폴더에서 관리하고, 보관된 v1 기록은 과거 버전 확인이 필요할 때만 별도 루트로 복원한다.

<!-- BEGIN ui-craft (managed — do not edit) -->
# ui-craft skill

The ui-craft skill is installed at: /Users/sewon/.codex/skills/ui-craft

Load it at the start of any UI design or implementation task.
<!-- END ui-craft -->
