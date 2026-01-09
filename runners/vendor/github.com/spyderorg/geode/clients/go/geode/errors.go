package geodesql

type DriverError struct {
	StatusClass string
	Code string
	Message string
	Anchor string
	Additional []string
	FlaggerFindings []string
}

func (e *DriverError) Error() string { return e.Code+": "+e.Message }
