Dependency audit maintenance, 4 November 2026
===========================================

The canonical runtime and constraint pins now select pypdf 6.21.4. Both the
installed application tree and its constraints are audited separately. The
7 advisories published after the former 6.21.2 update must be absent.

The frontend keeps its existing ESLint/React-Hooks toolchain. Its development
dependency Minimatch 3.1.5 is incorrectly included in the registry range for
GHSA-g3hv-75wg-m249. The maintainer describes `firstPhasePreProcess` and
`optimizationLevel` in 10.2.6. Neither exists in the installed legacy-v3 code.

Sources:

- https://github.com/isaacs/minimatch/security/advisories/GHSA-g3hv-75wg-m249
- https://github.com/advisories/GHSA-g3hv-75wg-m249

Run `node scripts/auditDependencies.mjs` from frontend. It still runs the full
`npm audit --json --audit-level=low`, stores the raw report plus the decision in
`frontend/artifacts/npm-audit`, and fails for every unreviewed advisory. The
single exception additionally requires the exact advisory metadata, version
3.1.5, development-only lockfile entry, original entrypoint, exact source SHA-256,
and absence of the affected preprocessing routines. Version 10.2.6, changed
source, a new advisory, incomplete/network results, and ungrounded graph cycles
all fail. Audit suppression flags and blanket exclusions are not used.

The exception expires on 4 December 2026. Before then, recheck the upstream
advisory range and remove the exception as soon as its registry metadata is
corrected. The helper accepts a vulnerability-free report without requiring an
exception or an installed Minimatch package.

The embedded Temurin runtime and matching OpenJDK source archive are updated to
21.0.13+9 using the official release asset SHA-256 values. This is a separate
maintenance surface from npm/Python audits. Adoptium's release notes confirm the
NSS 3.131.1 trust-store correction; the unaffected G1 root must not be confused
with the removed compromised intermediate issuers. The application validator
continues to run without network/socket permission.

- https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.13%2B9
- https://github.com/adoptium/temurin/issues/317
