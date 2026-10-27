module gitlab.com/devnw/geode/geode-test-harness/runners

go 1.27.3

require (
	geodedb.com/geode v1.0.0
	github.com/quic-go/quic-go v0.63.0
	gopkg.in/yaml.v3 v3.0.1
)

replace geodedb.com/geode => ../../geode-client-go

require (
	golang.org/x/crypto v0.58.0 // indirect
	golang.org/x/net v0.61.0 // indirect
	golang.org/x/sys v0.49.0 // indirect
	golang.org/x/text v0.43.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20261005182115-fad411399dd8 // indirect
	google.golang.org/grpc v1.84.0 // indirect
	google.golang.org/protobuf v1.36.12 // indirect
)
