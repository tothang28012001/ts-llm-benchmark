# Isolated, reproducible environment for benchmarking one repository.
# Every repository is analysed in a fresh container from this image, so its
# install scripts, tests and mutants never touch the host.
FROM node:22-bookworm

ENV CI=true \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    COREPACK_ENABLE_STRICT=0 \
    HUSKY=0 \
    PUPPETEER_SKIP_DOWNLOAD=1 \
    PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    CYPRESS_INSTALL_BINARY=0 \
    ELECTRON_SKIP_BINARY_DOWNLOAD=1 \
    NODE_OPTIONS=--max-old-space-size=6144

RUN corepack enable \
 # old lockfiles reference GitHub dependencies over SSH; fetch them anonymously over HTTPS instead
 && git config --global url."https://github.com/".insteadOf "ssh://git@github.com/" \
 && git config --global --add url."https://github.com/".insteadOf "git@github.com:"

# Pinned analysis toolchain (identical for every repository)
WORKDIR /tools
COPY tools/package.json tools/package-lock.json ./
RUN npm ci --ignore-scripts && npm cache clean --force
COPY tools/*.mjs ./

# StrykerJS, nested layout (each package carries its own dependencies), peers left to the project
WORKDIR /stryker
RUN npm init -y >/dev/null && npm install --install-strategy=nested --legacy-peer-deps --ignore-scripts       @stryker-mutator/core@10.1.1 @stryker-mutator/vitest-runner@10.1.1       @stryker-mutator/jest-runner@10.1.1 @stryker-mutator/mocha-runner@10.1.1 && npm cache clean --force

WORKDIR /work
