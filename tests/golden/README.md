# Golden hashes

One file per (profile, logical date), holding the SHA-256 of every output table
for that run.

`ob verify` rebuilds the date from the landing zone and compares. A mismatch is
a build failure: the pipeline produced different bytes from the same inputs.

Re-record with `make golden` — and read the diff. A moved hash is either a
deliberate change to what we extract, or ambient nondeterminism leaking into a
transform. The PR has to say which.
