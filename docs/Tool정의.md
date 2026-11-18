# 금융 조회 Tool 정의서

등록 계약은 은행별 `GET /api/tools`가 반환한다. 은행별로 하나의 등록 계좌를 제공하는 로컬 시연 환경이다. 통화는 원화이며 계좌·잔액 조회는 요청 시점의 고정 합성 원장을 읽는다. 기간별 과거 거래내역은 조회하지 않는다.

| 함수 | 필수 입력 | 성공 응답의 data | 실패 결과와 후속 처리 |
|---|---|---|---|
| list_accounts | 없음 | 계좌 후보 배열. account_id와 product_name | 빈 후보면 상세 조회를 생략하고 계산을 보류 |
| read_balance | account_id 문자열 | available 정수 원 | UNKNOWN_ACCOUNT, MISSING_AMOUNT, UPSTREAM_ERROR. 확인되지 않은 값을 0원으로 대체하지 않는다. |
| search_branches | region 문자열 | 최대 세 개의 name, address, url | BAD_ARGUMENT, MISSING_KEY, NO_RESULT, UPSTREAM_ERROR. 잔액 조회가 함께 요청된 경우 성공한 금액을 유지한다. |

성공은 `{"ok":true,"source":"mock","data":{"available":205000000}}`, 실패는 `{"ok":false,"code":"MISSING_KEY"}`처럼 표현한다. 지점 검색 성공 출처는 kakao다. 카카오 요청은 지역과 KB국민은행 이름, 은행 카테고리로 구성한다. B은행은 가상의 은행이므로 검색 안내 대상도 KB 지점이다. [함수 스키마·구현](../backend/app/tools.py)

## 오픈뱅킹 필드와 합성 원장

잔액 응답에는 as_of 기준 시각을 담는다. 상세 조회 시 등록 ID와 기관·은행 성공 코드를 함께 검사한다. 여러 후보가 들어오면 같은 ID를 한 번만 조회하고 성공한 잔액만 합산한다. 확인하지 못한 계좌는 제외 건수를 답변에 표시한다.

| 외부 명세에서 확인할 값 | 로컬 표현 | 사용처 |
|---|---|---|
| 계좌 후보와 이용자의 사전 등록 정보 | kb-demo-01 또는 b-demo-01 | 목록에서 나온 자기 은행의 account_id만 상세 조회한다. 실제 연동은 핀테크이용번호와 고객 동의 토큰이 필요하다. |
| rsp_code와 은행 응답 코드 | A0000, 000 | 성공 모킹 응답에 표시한다. 다른 은행 ID로 조회하면 404가 발생한다. |
| balance_amt와 available_amt | 각각 숫자 문자열 | 자기자금 계산은 available_amt를 정수 원으로 검증한 뒤 사용한다. 누락·음수·숫자 형식 오류는 보류한다. |
| 카카오 documents | place_name, address_name, place_url | 실제 공급자가 반환한 상호·주소·장소 URL을 화면에 표시한다. |

## 외부 API 연동

KB 상담 API에서 “영통에서 상담할 은행 지점을 찾아줘”라고 요청하자 GMS가 `search_branches`를 선택했고, 카카오는 KB국민은행 지점 3곳의 이름·주소·장소 링크를 반환했다. [실호출 결과](검증.md#영통-지점-검색-실호출)

공개 명세 확인일은 2026-11-18이다. 금융 조회의 외부 호출량은 0이다. 카카오 키는 서버 환경변수로만 읽고 요청당 장소 검색 1회, 타임아웃 5초를 적용한다. 이 시험에서 두 공급자의 인증 요청은 성공했다. 계정별 호출 한도와 잔여량은 측정하지 않았다. [금융결제원 계좌통합조회](https://developers.kftc.or.kr/dev/openapi/account-info) · [잔액조회](https://developers.kftc.or.kr/dev/openapi/open-banking/balance) · [카카오 로컬 API](https://developers.kakao.com/docs/ko/local/dev-guide) · [카카오 쿼터](https://developers.kakao.com/docs/ko/getting-started/quota)

새 Tool은 `CATALOG`에 함수 설명과 입력 JSON 스키마를 등록하고 call에 검증·오류 변환을 구현한다. Agent에서 선행 입력과 결과 소비 경로를 연결한 뒤 성공·키 누락·결과 없음·시간 초과를 각각 시험한다.

2026-11-18 확인한 카카오 공개 쿼터 표에는 키워드 장소 검색 무료 일간 제공량이 100,000건으로 기재돼 있다. 카카오맵 무료 쿼터는 개발자 계정에서 처음 활성화한 앱에 적용되며 실제 사용량은 앱 관리 페이지에서 확인한다. [카카오 쿼터와 적용 조건](https://developers.kakao.com/docs/ko/getting-started/quota)

[프로젝트 홈](../README.md) · [Agent의 도구 선택](Agent설계.md#상담-처리)
