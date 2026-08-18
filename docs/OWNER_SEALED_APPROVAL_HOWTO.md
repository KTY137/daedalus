# Approving a promotion, as the owner

Iron Plan: ALIGNED · Iron Gate: 0 · invariants §4.5 (sealed promotion),
§4.3 (isolation), §4.8 (bounded effects).

This is the option-B trust root from `docs/GATE0_SEALED_OWNER_APPROVAL.md`:
you sign an annotated Git tag with your own signing key, and the promotion
boundary verifies that signature against a list of principals committed to
this repository.

The property being bought is narrow and worth stating plainly: **approving a
promotion requires something only you hold.** No agent, no script in this
repository, and no process running as you can produce an approval, because
none of them can produce your signature.

---

## 0. What you only have to do once

### Mint a signing key

Use a key reserved for this. Do not reuse an authentication key, and give it a
passphrase — the passphrase is what stops a process running as you from
signing silently.

```sh
ssh-keygen -t ed25519 -C "owner@daedalus" -f ~/.daedalus-keys/owner-approval
```

Keep the private half out of this repository forever. Nothing in the tree ever
reads it; the verifier only ever sees public keys.

### Commit the public half

Add one line to `configs/owner-allowed-signers`, in the ssh-keygen
ALLOWED SIGNERS format:

```
owner@daedalus ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA... owner@daedalus
```

The principal on the left must equal the `user.email` you tag with.

That file ships with **no principals**, so promotion approval is refused until
you do this. That is deliberate. It is also the single most security-relevant
line in the repository:

> Whoever is named there can approve a promotion. The verifier reads this file
> from the committed object, not from your working copy, so a change to it is
> a reviewed commit and nothing else. Give that commit its own review, and put
> the key fingerprint in the message.

Confirm the fingerprint you committed matches the key you hold:

```sh
ssh-keygen -lf ~/.daedalus-keys/owner-approval.pub
```

---

## 1. Approving one promotion

### Look at what you are being asked to approve

```sh
python scripts/owner_approval_request.py show \
    --candidate-sha256  <candidate artifact sha256> \
    --evidence-sha256   <evidence packet sha256> \
    --nomination-sha256 <nomination receipt sha256> \
    --base-revision     <revision the candidate was built on> \
    --target-ref        <branch being promoted onto> \
    --target-revision   <that branch's current HEAD> \
    --ttl-hours         2
```

This prints the byte-exact body, its SHA-256, and the exact `git tag` command.
It signs nothing and holds no key. **Read the body before you sign it** —
that string is the entire content of your approval, and every field in it is
a thing you are asserting.

### Sign it

Run the printed command yourself, in your own shell:

```sh
git -c gpg.format=ssh -c user.signingkey=~/.daedalus-keys/owner-approval \
    tag -s -m '<the exact body printed above>' \
    owner-approval/<id>
```

Paste the body exactly. A re-typed or reformatted body is a different body,
and it will be refused — the verifier compares bytes, not intent.

### Confirm what the repository now holds

```sh
python scripts/owner_approval_request.py inspect --tag owner-approval/<id>
```

The SHA-256 printed here must equal the one you were shown before signing. If
it does not, something changed between reading and signing; do not proceed.

---

## 2. What the approval is bound to, and what that buys

| bound to | replay it prevents |
|---|---|
| `purpose` | a tag you signed for anything else counting as a promotion approval |
| candidate artifact sha256 | approving candidate A and promoting candidate B |
| evidence packet sha256 | approving on evidence E and promoting on weaker E′ |
| `base_revision` | approving a candidate built on a different base |
| `target_ref` + `expected_target_revision` | promoting onto a branch that moved after you looked |
| `expires_at` (max 24h) | an approval becoming a standing authorisation |
| `nonce` | the ledger recognising a second use of one approval |

The target-revision binding is the one that will most often refuse you. If the
branch moves between your reading and the promotion, the approval is void and
you get to look again. That is the intended behaviour, not a defect: the
alternative is approving a merge base you never saw.

---

## 3. What this does not protect against

Stated plainly, because a security note that only lists its wins is not
useful.

- **An unlocked key.** If your private key has no passphrase and sits on a
  machine an agent controls, that agent can sign. The passphrase is doing real
  work here.
- **A bad review of the signers file.** Anyone who can land a commit adding a
  principal to `configs/owner-allowed-signers` can approve promotions from
  then on. This trust root is exactly as strong as the review of that one
  file. Measured: verifying an attacker-signed tag against an
  attacker-supplied signers file returns "Good signature", exit 0.
- **Approving without reading.** Every binding above is a claim *you* make.
  The mechanism guarantees the claim is yours; it cannot make it true.
- **Anything outside this boundary.** This authenticates the approval. It does
  not sandbox the candidate, and it is not a general answer to a compromised
  machine.

---

## 4. Where each piece lives

| what | where |
|---|---|
| trust root (committed principals) | `configs/owner-allowed-signers` |
| verifier | `daedalus/kernel/signed_approval.py` |
| owner tool (never signs) | `scripts/owner_approval_request.py` |
| fault injection | `tests/kernel/test_signed_approval_trust_root.py` |
| mutation campaign | `scripts/run_signed_approval_trust_root_mutations.py` |
| your private key | outside the repository, and it stays there |
