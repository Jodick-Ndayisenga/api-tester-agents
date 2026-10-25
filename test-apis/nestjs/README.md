# NestJS target

## Setup

Install Node.js 18 or newer, then from this directory run:

```bash
npm install
```

## Start

```bash
npm run start:dev
```

The API listens on `http://localhost:8003`. Use `PORT=9000 npm run start:dev`
to select another port.

Run the tester from the repository root:

```bash
api-tester run -s test-apis/nestjs/api-spec.yaml -u http://localhost:8003
```
