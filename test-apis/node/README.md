# Plain Node.js target

This fixture uses only Node.js built-in modules, so it has no runtime package
dependencies.

## Start

```bash
npm start
```

The API listens on `http://localhost:8002`. Override the port with `PORT=9000
npm start`.

Run the tester from the repository root:

```bash
api-tester run -s test-apis/node/api-spec.yaml -u http://localhost:8002
```
