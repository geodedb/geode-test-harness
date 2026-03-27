module gitlab.com/devnw/geode/geode-test-harness/runners

go 1.25.0

require (
	geodedb.com/geode v1.0.0
	gopkg.in/yaml.v3 v3.0.1
)

replace geodedb.com/geode => ../../geode-client-go

require (
	github.com/kr/text v0.2.0 // indirect
	github.com/quic-go/quic-go v0.59.0 // indirect
	golang.org/x/crypto v0.49.0 // indirect
	golang.org/x/net v0.51.0 // indirect
	golang.org/x/sys v0.42.0 // indirect
	golang.org/x/text v0.35.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20251202230838-ff82c1b0f217 // indirect
	google.golang.org/grpc v1.79.3 // indirect
	google.golang.org/protobuf v1.36.10 // indirect
)
