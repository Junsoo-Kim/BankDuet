# API 명세

외부 기본 경로는 `http://localhost:18473/{bank}/api`다. bank는 kb 또는 b다. 각 은행에서 POST /session을 호출하면 해당 은행 경로의 HttpOnly 시연 쿠키가 발급된다. 은행당 한 명의 고정 가상 고객을 제공한다. FastAPI가 생성한 [전체 요청·응답 스키마](evidence/openapi.json)와 [KB Swagger](http://localhost:18473/kb/api/docs)를 함께 제공한다.

## 공동 목표와 승인

| 메서드와 경로 | 입력 | 결과 |
|---|---|---|
| POST /plans · GET /plans · GET /plans/{id} | 생성 시 title, target, months, mode | 201 목표 생성, 목록, 상세 및 자행 private와 공동 forecast |
| PUT /plans/{id} · DELETE /plans/{id} | 개설 은행에서 수정 시 최신 version과 조건 | 수정안 발행 또는 양쪽 목록에서 제외 |
| POST /plans/{id}/consent | mode = once, auto, revoked | 기여액 공유·갱신·철회 |
| PUT /plans/{id}/budget | reserve, monthly (원) | 자행 비상금과 예정 납입액 수정 |
| POST /plans/{id}/expenses · POST /plans/{id}/expenses/{expense_id}/post | 등록 시 지출 id(UUID), amount, note | 사유를 자행에 보관. 동일 ID 재요청·출금 처리 시 중복 차감 방지 |
| POST /plans/{id}/missed · POST /plans/{id}/deposits | month, 실납입은 amount 추가 | 누락 또는 실제 납입 기록. 같은 회차의 다른 금액 재입력은 409 |
| GET /plans/{id}/trajectory | 목표 ID | 0회차부터 목표일까지 매월 예상 원금과 달성률 |
| POST /plans/{id}/versions/{v}/decisions | choice = approve, reject, extend | 투표·거절·기간 연장 요청. 타행 요청의 최종 반영은 SSE로 확인 |

## 상담·일정·실행 기록

| 메서드와 경로 | 입력 | 결과 |
|---|---|---|
| POST /chat/runs · GET /chat/runs/{id} | session_id, message, 선택 plan_id | 202 실행 ID 후 상태와 답변 조회 |
| GET /chat/sessions/{id} · GET /tools | 세션 ID 또는 없음 | 대화 이력 또는 등록 Tool 스키마 |
| GET·POST /appointments · GET·PUT·DELETE /appointments/{id} | title, starts_at, ends_at. 시간대 포함 ISO 8601 | 일정 조회·생성·수정·삭제. 겹치면 저장 결과에 conflicts를 포함 |
| GET /logs · GET·DELETE /logs/{sid} | 세션 ID | 세션 목록, 순번별 이벤트 또는 로그 삭제 건수. 업무 기록은 유지 |
| GET /logs/{sid}/evaluation · POST /logs/{sid}/diagnosis | 세션 ID | 실행별 규칙 판정, 이상이 있을 때만 모델 진단 시도 |
| GET /events/cursor · GET /events | after 또는 Last-Event-ID | 현재 커서, text/event-stream. 재구독 시 이전 순번 이후 이벤트 전송 |

## 오류 응답

오류는 `detail`을 포함한다. 401은 자행 시연 세션 없음, 403은 타행 목표 삭제 등 권한 밖 요청, 404는 대상 없음, 409는 이전 버전·유효하지 않은 동의·중복 상태 충돌, 422는 입력 범위 오류다. 상대 최신 동의의 확인이 실패하면 확정을 보류하고 503을 반환하거나 큐에서 재시도한다.

## 은행 내부 협의

고객 웹 프록시는 은행 간 전용 경로를 공개하지 않는다. 송신 측은 Agent Card의 coordinate-goal 스킬과 HTTP+JSON 인터페이스를 확인한 뒤 Bearer 자격으로 POST /message:send를 호출한다. 같은 목표에는 동일한 contextId를, 각 발송에는 별도 messageId를 사용한다. 수신 측은 Task ID와 상태를 반환한다. GET /tasks/{task_id}로 작업 상태를 읽을 수 있다. 금융 합의 상태(검토·확정)는 업무 페이로드에 보관한다. 협의가 끝난 목표도 변경될 수 있어 A2A 작업은 삭제 전까지 추가 입력을 받는다.

| 메시지 | 방향 | 내용 |
|---|---|---|
| snapshot | 개설 은행 → 상대 | 목표 ID·조건·버전·동의한 기여액·승인 및 확정 이력 |
| share | 참여 은행 → 개설 은행 | 기여액 스냅숏 또는 철회, 공유 리비전 |
| decision | 참여 은행 → 개설 은행 | 버전과 approve, reject, extend 중 한 결정 |

SSE의 plan 이벤트는 목표 ID와 변경을 알린다. 금액·승인 결과는 자행 권한으로 최신 목표를 다시 조회한다. run.progress와 run.done은 실행 ID와 세션 ID로 구분한다. [전송 구현](../backend/app/transport.py) · [브라우저 구독](../frontend/src/BankView.vue)

[프로젝트 홈](../README.md) · [Agent 설계](Agent설계.md)
