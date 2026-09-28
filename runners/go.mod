module gitlab.com/devnw/geode/geode-test-harness/runners

go 1.27.1

require (
	geodedb.com/geode v1.0.0
	github.com/quic-go/quic-go v0.61.0
	gopkg.in/yaml.v3 v3.0.1
)

replace geodedb.com/geode => ../../geode-client-go

require (
	github.com/kr/text v0.2.0 // indirect
	golang.org/x/crypto v0.55.0 // indirect
	golang.org/x/net v0.58.0 // indirect
	golang.org/x/sys v0.47.0 // indirect
	golang.org/x/text v0.41.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20260526163538-3dc84a4a5aaa // indirect
	google.golang.org/grpc v1.83.2 // indirect
	google.golang.org/protobuf v1.36.12 // indirect
)
