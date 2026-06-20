# Firebase emulator suite (auth + firestore). Needs a JRE (firestore emulator is
# a JVM process) + the Firebase CLI. ⚠️ unverified — see docker-compose.yml.
FROM node:20-bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends default-jre-headless curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN npm install -g firebase-tools@15
WORKDIR /app
# Emulator config: bind 0.0.0.0 so other containers + the host can reach it.
COPY apps/web/firebase.json /app/firebase.json
RUN node -e "const fs=require('fs');const c=JSON.parse(fs.readFileSync('/app/firebase.json','utf8'));c.emulators={auth:{host:'0.0.0.0',port:9099},firestore:{host:'0.0.0.0',port:8088},ui:{enabled:true,host:'0.0.0.0',port:4001},singleProjectMode:true};delete c.functions;delete c.hosting;fs.writeFileSync('/app/firebase.json',JSON.stringify(c,null,2));"
EXPOSE 9099 8088 4001
