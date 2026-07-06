# policy/ — security requirements for the helpdesk app

Unlike the extraction corpus (where policy/ ships empty), this greenfield
package POPULATES policy/security.yaml because the requirements are part of
the app's intent. Machine-verifiable requirements name their enforcing gate;
deployment-only requirements (TLS, at-rest cipher, cookie flags) are marked
for L3 attestation rather than local L2.

Key executable requirement: Argon2id at m=19456,t=2,p=1 is gated by INV-002
because the parameters live in the hash string itself — the strongest kind of
policy contract, one that cannot be satisfied by a build that merely claims
compliance.
