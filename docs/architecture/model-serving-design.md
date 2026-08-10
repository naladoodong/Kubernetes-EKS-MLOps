# ArgMax Mini Model Serving Design

| 영역 | 결정 |
|---|---|
| ModelVersion | immutable 학습 결과 |
| Deployment binding | `model_version_id` immutable |
| Runtime | `argmax-tabular-runtime-v1` |
| Serving mode | KServe Standard Mode |
| Routing | `kserve_namespace + kserve_service_name` |
| `endpoint` | 관측 metadata |
| Serving 가능 상태 | READY, UPDATING |
| Traffic split | 초기 미지원 |

## 범위

ModelVersion은 특정 TrainingJob의 불변 결과이고 InferenceDeployment는 생성 뒤 같은 `model_version_id`에 고정된다. 새 버전 배포는 새 Deployment 생성으로만 한다. in-place 교체, alias, canary·traffic split·자동 승격은 초기 범위에서 제외한다.

## Training target과 ModelInterface

TrainingJob은 `target_column_id`를 보존한다. 서비스 계층은 target의 dataset_version이 요청 DatasetVersion과 같고 type이 UNKNOWN이 아님을 검증한다. 알고리즘 registry는 코드의 versioned constant이며 target·feature 지원 타입, artifact format, serving runtime, hyperparameter schema, output contract를 제공한다.

ModelInterface는 Draft 2020-12의 instance 1건 input schema와 prediction 1건 output schema를 저장한다. batch envelope는 저장하지 않는다. feature는 target·UNKNOWN을 제외한 DatasetColumn이며 name 그대로 property로 쓰고 모든 feature는 required, `additionalProperties=false`다. nullable은 null 허용으로 표현하며 `x-argmax-logical-type`은 최상위 annotation이다. `x-argmax-feature-order`는 ordinal_position ASC를 명시한다.

초기 runtime feature 허용 타입은 INTEGER, FLOAT, BOOLEAN, CATEGORY다. 알려진 미지원 타입은 제외하지 않고 `UNSUPPORTED_FEATURE_COLUMN_TYPE`으로 요청을 거절한다. feature가 없으면 `NO_USABLE_FEATURE_COLUMNS`이다. regression 출력은 number `value`이며, classification probabilities는 최소 2개·중복 label 없음·0..1·NaN/Infinity 금지·합계 오차 0.001 이내를 검증한다.

## Artifact와 Runtime

초기 bundle은 manifest.json, interface.json, preprocessing.json, classifier용 labels.json, `model.json`으로 구성한다. `model.json`은 XGBoost artifact이며 arbitrary pickle/joblib 업로드는 금지한다. labels.json은 같은 primitive 타입(string, boolean, integer)의 중복 없는 순서 배열이며 probability index와 대응한다. preprocessing은 선언형 변환만 허용하며 사용자 코드·pickle·dynamic import는 금지한다.

Custom ClusterServingRuntime은 `argmax-tabular-runtime-v1`, KServe format은 `argmax-tabular` v1이다. 초기 CPU runtime은 XGBoost `model.json`만 지원한다. GPU는 모든 학습 과정의 요구사항이며 serving execution device와는 별개이므로 초기 tabular serving은 CPU를 사용한다. scikit-learn/joblib 및 generic sklearn runtime은 future extension이다. registry, manifest, KServe runtime의 runtime profile은 모두 `argmax-tabular-runtime-v1`이어야 하며 불일치는 `RUNTIME_MAPPING_CONFLICT`다.

## Deployment Controller

min/max replicas는 desired, applied_*는 마지막 Ready 확인값이다. operation_started_at은 DEPLOYING·UPDATING·DELETING timeout 기준이며 retry 중 갱신하지 않는다. Controller는 watch fast path와 60초/100건 periodic reconciliation을 사용한다. READY resource 유실 또는 immutable drift는 DEPLOYING, replica-only drift는 UPDATING으로 전이한다. DELETING timeout은 FAILED다.

endpoint는 관측·운영 metadata이며 Gateway의 routing 기준이 아니다. Inference Gateway는 유일한 external inference application boundary이고, Gateway는 kserve_namespace와 kserve_service_name으로 결정적 cluster-local ClusterIP Service를 호출한다. KServe InferenceService는 별도 public inference endpoint를 제공하지 않는다. traffic_config_json은 `{}`만 허용한다.

생성은 API의 DB-local validation 뒤 `PENDING`과 202 응답으로 끝나며, Controller가 `PENDING → DEPLOYING`에서 manifest·runtime·interface·checksum을 검증하고 KServe readiness 뒤 READY로 전이한다. CREATE/UPDATE/ROLLBACK/DELETE timeout은 각각 900/300/300/600초이고 모두 operation_started_at을 기준으로 한다. Update 실패는 desired를 마지막 applied 값으로 되돌린 뒤 rollback하며 rollback 실패에도 applied 값은 마지막 검증 성공값을 유지한다. NotFound 삭제는 멱등 성공이고 resource 부재 확인 뒤 DELETED로 전이한다.

## Inference Gateway

READY와 UPDATING만 추론 가능하다. 매 요청 deployment ownership/status와 Model 삭제 여부를 RDS에서 확인하고 ModelInterface만 30초 local cache할 수 있다. predict envelope는 instances 배열이며 최대 100건, 1 MiB다. KServe 호출은 자동 재시도 없이 전체 10초(connect 1초/read 8초)다. 응답 개수·output schema·classification semantics 위반은 `INVALID_SERVING_RESPONSE`다. raw request/prediction은 RDB에 저장하지 않는다.

대표 오류는 401 UNAUTHORIZED, 404 RESOURCE_NOT_FOUND, 409 DEPLOYMENT_NOT_READY/FAILED/DELETING, 413 REQUEST_BODY_TOO_LARGE, 422 INPUT_SCHEMA_VALIDATION_FAILED/BATCH_SIZE_EXCEEDED, 503 SERVING_UNAVAILABLE 또는 SERVING_CONFIGURATION_INVALID, 504 SERVING_TIMEOUT, 502 INVALID_SERVING_RESPONSE다. SERVING_CONFIGURATION_INVALID는 UNSUPPORTED_MODEL_INTERFACE_VERSION 같은 configuration integrity 오류다. InferenceLog는 async buffered writer를 통해 S3 Parquet·Glue·Athena로 보낸다. ModelInterface input validation, serving, Gateway output validation이 모두 성공한 정상 inference는 metadata와 validated input/output을 `input_payload_json`, `output_payload_json` JSON-compatible analytical payload로 적재한다. input validation 실패는 error/metadata만 기록하며 invalid raw input은 저장하지 않는다. validation 뒤 serving timeout·unavailable·error 또는 `INVALID_SERVING_RESPONSE`에서는 validated input과 error metadata만 기록하고 output payload는 저장하지 않으며 invalid raw serving output도 저장하지 않는다. 이는 application/structured operational log와 분리된 분석 데이터셋이다. Authorization, Cookie, JWT/token, credential, Secret, presigned URL, internal infrastructure URI, HTTP header 원문, artifact URI, Kubernetes 식별자, stack trace는 InferenceLog에도 저장하지 않으며, 적재 실패는 추론 결과에 전파하지 않는다.
