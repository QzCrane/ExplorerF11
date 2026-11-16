# Code signing

The release binaries are not signed. This document states what signing would
and would not change, what it costs, and how it would be wired in, so the
decision can be made on numbers rather than on the phrase "no more warnings".

Short version: signing is worth doing for the identity it puts on the file, not
for the warning it removes. It does not remove the warning on a new release. No
certificate does, since 2024.

## What a signature is

An Authenticode signature is a PKCS#7 block appended to the PE image and
referenced from its security data directory. It holds a digest of the image, the
publisher's certificate, and — if you use a timestamp authority, which you must
— a countersignature proving the signing happened while the certificate was
valid. The digest is what makes tampering detectable: modify one byte and the
signature no longer verifies.

`EF11_SIGN_CMD`, if set, receives the file to sign in `EF11_FILE` and must
rewrite it in place. `tools/release.py` treats an empty security directory after
that command as a failure, so a signing step that silently does nothing cannot
produce a release.

`tools/check_release_facts.py` reads the same directory, so the documentation and
the binary cannot disagree about whether this build is signed.

## What it changes for the user

| | unsigned | signed, no reputation yet | signed, reputation established |
|---|---|---|---|
| What Windows shows | "Windows protected your PC" - a block, behind "More info" | "Unknown publisher" with your name, one extra click | no prompt |
| Publisher identity | none | name on the certificate | same |
| Tamper detection | SHA-256 only, which you must compare by hand | signature verifies on open | same |
| Enterprise / EDR policy | often blocked outright | usually allowed | allowed |

The middle column is the honest description of the first months after buying a
certificate. SmartScreen reputation is per-publisher and accumulates from
downloads and clean runs; a new certificate starts at zero. Microsoft states
this plainly, and the CAs repeat it: EV certificates have not bypassed SmartScreen
since 2024, so the old advice "buy EV and the warning disappears" is out of date.

What signing does buy immediately is the first and third rows. A user who clicks
"More info" sees `QzCrane` rather than "Unknown publisher", and an
administrator can allow-list a publisher instead of a hash that changes every
release. For a tool that asks to run at logon, that is the part that matters.

## What it costs

Prices checked November 2026; they move, and the resale channel matters more
than the list price.

| Option | Cost | Eligible | Verdict for this project |
|---|---|---|---|
| Azure Artifact Signing (formerly Trusted Signing) | $9.99/month, 5000 signatures; $99.99/month, 100k | Organizations in US/CA/EU/UK; **individuals in US/CA only** | Not available: an individual in China cannot enrol |
| Certum Open Source Code Signing, cloud (SimplySign) | about €49/year | Natural person, non-commercial open source project; MIT on GitHub qualifies | **The only affordable route that fits** |
| Commercial OV certificate | $150-300/year, or about ¥800-1200/year through a Chinese reseller | anyone who passes identity validation | Viable, same SmartScreen behaviour as the row above, more expensive |
| EV certificate | $400+/year | anyone who passes extended validation | Pays for identity checks and driver signing; no longer buys an instant bypass |
| Self-signed certificate | free | nobody | Worse than unsigned: it fails validation *and* still warns |

Two constraints that decide it:

- **Azure Artifact Signing is closed to individuals outside the US and Canada.**
  It is the cheapest and the only one with no hardware token, and it is not
  available here. No amount of configuration changes that.
- **Certificate lifetime is capped at about 460 days** by the CA/Browser Forum
  rules that took effect in March 2026. Any plan is an annual renewal, not a
  one-off purchase, and the release process must keep working across a renewal
  where the certificate serial changes but the publisher name does not.

Certum's open-source certificate is OV level: it validates a natural person, not
an organisation, and the publisher name in the signature is that person's real
name (`Open Source Developer, <name>`). That is acceptable for a tool published
under a personal account, but it is a fact to decide on, not a detail.

## What it would cost in this repository

The signing hook exists; the work is in the facts, not the code.

1. Buy the certificate and complete identity validation (1-3 business days).
2. Store the cloud-signing credentials as repository secrets; the CI job and the
   release machine both need them.
3. Set `EF11_SIGN_CMD` to the signing command. The release script signs between
   the build and the first measurement, so every published number describes the
   signed file.
4. The binary grows by the signature and its certificate chain - expect a few
   KB, not tens of KB. `make refresh-facts` re-derives `SIZE_KIB`, then the gates
   name every document that still quotes the old size.
5. Remove the "unsigned" statements. `check_release_facts.py` fails if the
   binary is signed and any of them survives:

   | File | What it says |
   |---|---|
   | `README.md` | one unsigned 411 KiB executable; not code-signed; SmartScreen will warn |
   | `README.zh-CN.md` | 二进制未做代码签名 |
   | `SECURITY.md` | not code-signed, so SmartScreen warns; the hash replaces a signature |
   | `docs/RELEASING.md` | the notes must state that the binary is unsigned |

6. Rebuild the screenshots only if the version string changed, which it will.
7. Reproducibility changes. `make -B` can no longer reproduce the published
   binary, because the signature needs a private key that only the signer holds.
   The published SHA-256 remains the integrity check; what is lost is the
   ability to rebuild and compare. `docs/RELEASING.md` states this where it
   currently promises that the tagged tree rebuilds the released hash.

Steps 4 through 7 are the reason this is one release's work and not an
afternoon's: they touch the number that appears in eleven places.

## Why not sign now

Nothing above is a reason to avoid it; the reason is that the benefit is
identity, and identity has no user until the tool has users. The current release
page states the situation plainly, publishes a SHA-256, and links to the source.
That is the honest position for an unsigned binary, and it stays honest only
while the documentation keeps saying so — which the gate now enforces.

The decision changes when one of these becomes true:

- the download count is high enough that "Unknown publisher" costs users;
- an organisation wants to deploy it and needs a publisher to allow-list;
- a false positive from a security product needs an appeal, which a signed
  binary makes possible.

Until then, `EF11_SIGN_CMD` stays unset, `docs/RELEASING.md` keeps requiring the
unsigned statement, and the signature check keeps the two in agreement.
