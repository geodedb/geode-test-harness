module gitlab.com/devnw/geode/geode-test-harness/runners

go 1.24.12

require (
	geodedb.com/geode v1.0.0
	gopkg.in/yaml.v3 v3.0.1
)

replace geodedb.com/geode => ../../geode-client-go

require (
	github.com/kr/text v0.2.0 // indirect
	github.com/quic-go/quic-go v0.59.0 // indirect
	golang.org/x/crypto v0.48.0 // indirect
	golang.org/x/net v0.49.0 // indirect
	golang.org/x/sys v0.41.0 // indirect
	golang.org/x/text v0.34.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20250825161204-c5933d9347a5 // indirect
	google.golang.org/grpc v1.75.1 // indirect
	google.golang.org/protobuf v1.36.10 // indirect
)
