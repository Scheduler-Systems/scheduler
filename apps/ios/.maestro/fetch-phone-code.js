// Fetch the most recent SMS verification code the Firebase Auth emulator issued for
// output.phoneNumber and expose it as output.smsCode. Runs HOST-side (Maestro), so it
// reaches the emulator at 127.0.0.1:9099 regardless of the device platform. The phone
// flow taps "Send" and asserts the code-entry screen BEFORE this runs, so the code exists.
// The Auth emulator runs in singleProjectMode under "demo-scheduler", so auth state buckets
// there regardless of the app's configured project id (scheduler-ci-placeholder).
var url = 'http://127.0.0.1:9099/emulator/v1/projects/demo-scheduler/verificationCodes'
var res = http.get(url)
var data = json(res.body)
var codes = data.verificationCodes || []
var code = ''
for (var i = 0; i < codes.length; i++) {
  if (codes[i].phoneNumber === output.phoneNumber) {
    code = codes[i].code   // keep scanning so the LAST (most recent) match wins
  }
}
output.smsCode = code
