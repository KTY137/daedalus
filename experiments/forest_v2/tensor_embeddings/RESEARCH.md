# Research basis: tensor-product embeddings

## Experiment status and boundary

This document supports work packet `EXPERIMENT-TENSOR-EMBEDDINGS-001` and the
frozen `forest-v2.tensor-embedding-experiment/1` specification. The work is an
isolated **EXPERIMENT** at active Gate 0 and is later-gate research prework. It
is not a production integration proposal.

Literature status was checked through 2026-08-24. No complete, current-`/2`,
independently isolated held-out baseline campaign has been run. The package can
therefore establish algebraic and structural properties only; it cannot emit a
scientific superiority, advance, or kill decision.

The only empirical claim under test is narrow:

> A pre-registered, separable plane/role contraction can rank revision-bound
> software artifacts better than flattened cosine over the exact same tensor
> entries, source bytes, candidates, and feature budget.

This is a comparison of a frozen **structure/kernel prior** with plain cosine.
It is not a claim that tensors are intrinsically more expressive or more
accurate than vectors. As derived below, the primary contraction is exactly a
bilinear score over the flattened 512-vector and, for the frozen kernels, an
ordinary dot product after a fixed linear feature transform.

Tensor scores remain regenerable retrieval proposals. Sources, source
revisions, Node Card identities, provenance, and Forest/Fourfold digests remain
authoritative. A score does not verify a claim, create a trusted
`CrossPlaneBinding`, change a Project Twin plane, or authorize promotion.
`automatic promotions: 0`

## Four different ideas that must not be conflated

The literature uses "tensor" for several mathematically related but
operationally different ideas. This experiment keeps them separate.

| Idea | Object represented | Operation | Role in this experiment |
| --- | --- | --- | --- |
| Tensor Product Representation (TPR) | One structured artifact as a sum of role/filler outer products | Linear tensor contraction | Primary representation and scoring claim |
| Multi-vector late interaction | One artifact as a matrix/set of local vectors | ColBERT: nonlinear `sum(max(dot))`; experiment: `mean(max(dot))` | Secondary retrieval arm only |
| Tensorized knowledge-graph embedding (KGE) | A global `head x relation x tail` fact tensor | Learned latent triple scoring | Literature context; not implemented or claimed |
| Tensor Train (TT) | A high-order tensor represented by chained cores | Exact or approximate storage/contraction | Exact CP-to-TT storage form only |

This distinction matters. A factored TPR contraction is not TT compression;
MaxSim is not a CP/Tucker factorization; and exact CP factors for an already
known artifact tensor are not a learned knowledge-graph embedding.

## What the Category-Theory part actually is

There is a precise categorical reading, but no magic extra algorithm. Because
the implementation uses chosen Euclidean inner products, transposes, and
vector/dual-vector pairings, the precise ambient setting is the dagger-compact
category of finite-dimensional real inner-product spaces and linear maps (the
real analogue of finite-dimensional Hilbert spaces), not merely an unspecified
symmetric monoidal category of vector spaces:

- the three axis spaces are objects `P`, `Role`, and `F`;
- a tensor embedding is a state (a linear map from the monoidal unit)
  `I ≅ ℝ -> P ⊗ Role ⊗ F`;
- outer products are the monoidal product, and addition combines bindings;
- the plane/role kernels are linear morphisms on `P` and `R`;
- the chosen inner products identify each coordinate space with its dual;
  feature matching uses the resulting cup/evaluation, and tensor contraction
  is ordinary categorical composition of the connected wires;
- CP, dense, and TT forms are different factorizations of the same morphism,
  so their diagrams must denote the same numerical map.

This is exactly the setting in which string diagrams provide a sound graphical
language for monoidal categories; Selinger's survey states the formal language
and its caveats ([Selinger, 2009](https://arxiv.org/abs/0908.3347)). The wider
connection between compositional processes and symmetric monoidal categories
is developed by [Baez and Stay,
2011](https://arxiv.org/abs/0903.0340), while categorical tensor-network states
are treated directly by [Biamonte, Clark, and Jaksch,
2010](https://arxiv.org/abs/1012.0531).

The directly relevant language-composition construction is DisCoCat:
[Coecke, Sadrzadeh, and Clark,
2010](https://arxiv.org/abs/1003.4394) map grammatical reductions into vector-
space morphisms so that contracting word tensors follows the grammatical
derivation. A recent learned example is
[DisCoCLIP](https://aclanthology.org/2025.starsem-1.25/), whose CCG-derived
tensor-network text encoder is trained for vision-language composition. Those
systems require a source grammar/category and a monoidal interpretation of its
types; their empirical results do not transfer to software-artifact retrieval.

What is **not** implemented is equally important: there is no general category
engine, no runtime objects/morphisms/functors, no natural-transformation or
adjunction machinery, no grammar or other source category, and no monoidal
functor that derives contractions from typed software syntax. Category theory
therefore supplies an interpretation and equivalence laws for the hand-written
tensor network; it is not an implemented DisCoCat pipeline and creates no
ranking evidence. The measurable retrieval hypothesis remains the concrete
multilinear contraction below. Building a generic categorical DSL here would
add a second abstraction layer without adding evidence.

## 1. Tensor-product representation and structured contraction

Tensor Product Representations bind a filler vector to the role that it fills.
For fillers \(f_i\) and roles \(r_i\), the order-two representation is

\[
S = \sum_i f_i r_i^\top.
\]

If \(u_j\) is dual to role \(r_j\), so that
\(r_i^\top u_j=\delta_{ij}\), then \(S u_j=f_j\). Thus identical fillers in
different roles need not collapse into the same bag representation. This is
the defining construction in [Smolensky's original TPR
paper](https://doi.org/10.1016/0004-3702(90)90007-M); the binding and unbinding
equations are presented accessibly in [Huang et al.,
2018](https://aclanthology.org/N18-1114.pdf).

The frozen experiment uses the direct order-three extension

\[
T = \sum_i w_i\,p_i\otimes r_i\otimes f_i,
\qquad T\in\mathbb R^{4\times4\times32},
\]

where the axes are exactly:

- plane: `code`, `type`, `data`, `knowledge`;
- role: `path`, `symbol`, `content`, `neighbor`;
- feature: 32 deterministic signed-hash subword features.

The dense tensor therefore contains exactly \(4\cdot4\cdot32=512\) scalars.
The primary numerator is the frozen separable contraction

\[
N(Q,D)=
\sum_{p,r,f,q,s}
Q_{prf}\,K^{(P)}_{pq}\,K^{(R)}_{rs}\,D_{qsf}.
\]

For globally L2-normalized \(Q\) and \(D\), the tight generic operator bound is

\[
|N(Q,D)|\le
\lVert K^{(P)}\rVert_2\,
\lVert K^{(R)}\rVert_2.
\]

The reference implementation does not compute those spectral norms. It uses
the conservative, inspectable upper bound

\[
b(K)=\sqrt{\lVert K\rVert_1\lVert K\rVert_\infty}
\;\ge\;\lVert K\rVert_2
\]

for each kernel and divides by \(b(K^{(P)})b(K^{(R)})\). For the frozen
matrices, each conservative bound is `2.5`, so the implemented denominator
factor is `6.25`; the product of the two spectral norms is approximately
`4.834`. The looser factor keeps the score bounded but is not a spectral-norm
normalization and does not make self-similarity equal to one. It is a
safety/calibration property, not evidence of retrieval quality. Because the
kernels and global tensor norms are fixed, this division cannot by itself
improve a ranking for a fixed query.

### Exact contraction from factors

The contraction need not materialize either tensor. If query and document are
stored as binding terms
\((a_i,p_i,r_i,f_i)\) and \((b_j,p'_j,r'_j,f'_j)\), respectively, then

\[
N(Q,D)=\sum_{i,j}a_i b_j
\bigl(p_i^\top K^{(P)}p'_j\bigr)
\bigl(r_i^\top K^{(R)}r'_j\bigr)
\bigl(f_i^\top f'_j\bigr).
\]

This is the selected **factored TPR plus structured contraction**. It directly
tests whether preserving the named axes and applying the pre-registered
compatibility matrices changes ranking under the frozen budget. In NumPy it
requires only dot products, matrix multiplication, and summation; dense
reference contractions can use
[`numpy.einsum`](https://numpy.org/doc/stable/reference/generated/numpy.einsum.html).

### Exact flattened-vector equivalence

Let \(x=\operatorname{vec}(Q)\), \(y=\operatorname{vec}(D)\), and use the
canonical `plane -> role -> feature` coordinate order. Then the same numerator
is

\[
N(Q,D)=x^\top M y,
\qquad
M=K^{(P)}\otimes K^{(R)}\otimes I_F.
\]

This identity is exact; tensor notation exposes the separable axes but does not
define a more expressive linear score. For any fixed \(M\), it can be evaluated
as the ordinary vector dot product \((M^\top x)^\top y\), so it is compatible
with an asymmetric maximum-inner-product-search formulation. The two frozen
kernel matrices are symmetric positive definite: their ordered leading
principal minors are respectively `(1, 3/4, 9/16, 3/8)` and
`(1, 7/16, 5/16, 453/1600)`, all positive, so Sylvester's criterion applies. If
\(M=A^\top A\), the numerator is also

\[
N(Q,D)=(Ax)^\top(Ay),
\]

an ordinary dot product after the same fixed linear transform on query and
document. The experiment's conservative denominator is not
\(\lVert Ax\rVert\lVert Ay\rVert\), so the implemented score is not cosine in
that transformed space; for unit-norm tensors it is a constant rescaling of
the transformed dot product.

Consequently, a win over *plain* flattened cosine can support only the claim
that the frozen plane/role compatibility prior helps this task. It cannot
support “tensor embeddings beat vector embeddings.” An implementation written
solely with flattened vectors and the same Kronecker-structured bilinear matrix
is an exact algebraic control, not a different scientific arm.

### The identity result is a required non-result

With \(K^{(P)}=I\) and \(K^{(R)}=I\),

\[
N(Q,D)=\langle Q,D\rangle_F
=\operatorname{vec}(Q)^\top\operatorname{vec}(D).
\]

After the same global L2 normalization, this is exactly cosine over the
flattened 512 entries. Consequently:

- identity contraction and flattened cosine must agree within `1e-10`;
- reshaping a vector and calling it a tensor cannot produce a gain;
- any real difference must come from the frozen non-identity plane/role
  kernels and retained bindings.

There is a second important equivalence. With orthogonal one-hot roles and an
identity role kernel, TPR similarity is just a sum of matching-role dot
products. It is then equivalent to an explicit per-role score fusion. TPR
provides an auditable binding representation, not automatically a richer
function. A future learned role kernel would likewise require comparison with
the same small bilinear role-weight matrix written without tensor terminology.

## 2. Why MaxSim is secondary

ColBERT represents a query and document by multiple normalized local vectors
and scores them using late interaction:

\[
\operatorname{MaxSim}(Q,D)
=\sum_{i=1}^{m_q}\max_{1\le j\le m_d}Q_i^\top D_j.
\]

This retains local alignment while allowing document vectors to be computed
offline. The equation and two-stage reranking procedure are defined in
[Khattab and Zaharia,
2020](https://people.eecs.berkeley.edu/~matei/papers/2020/sigir_colbert.pdf).

The experiment implements **Mean-MaxSim** over its non-zero query fibers:

\[
\operatorname{MeanMaxSim}(Q,D)
=\frac{1}{m_q}\sum_{i=1}^{m_q}\max_j Q_i^\top D_j.
\]

For one fixed query, division by \(m_q\) leaves document ranking unchanged, but
the numerical score and comparisons across queries differ from ColBERT's sum.
The implementation must therefore be described as a ColBERT-like mean
operator, not as an exact reproduction of ColBERT scoring.

MaxSim is a valuable comparator, but it is not the primary causal test here:

1. `max` is nonlinear and changes the aggregation rule, whereas the primary
   question concerns a declared linear plane/role contraction.
2. A multi-vector method can gain merely from storing more local matching
   opportunities. Fiber count, source bytes, and the underlying feature tensor
   therefore have to remain fixed.
3. MaxSim has \(O(m_qm_dd)\) exhaustive pair cost and \(O(m_dd)\) storage. Its
   probability of a high accidental match also grows with document fiber
   count.
4. The frozen signed-hash fibers are not contextual BERT token embeddings.
   This arm tests a **ColBERT-like operator**, not a reproduction of ColBERT's
   learned model or published effectiveness.

Storage is a real concern rather than a footnote. [ColBERTv2's primary
paper](https://aclanthology.org/2022.naacl-main.272.pdf) reports that uncompressed
multi-vector retrieval inflates index footprint by roughly an order of
magnitude in its setting and introduces centroid-plus-quantized-residual
compression. This experiment does not inherit those compression results. It
must report its own canonical bytes and latency, and MaxSim cannot rescue a
failed primary TPR claim.

Recent work reinforces the terminology boundary rather than removing it.
[Tensor Product Attention](https://arxiv.org/abs/2501.06425) factorizes
context-dependent query/key/value representations to reduce Transformer KV
cache cost; it is an attention-architecture and memory result, not a document
retrieval tensor score. [MetaEmbed](https://arxiv.org/abs/2509.18095) and
[jina-embeddings-v4](https://arxiv.org/abs/2506.18902) expose flexible or
joint single-/multi-vector late-interaction retrieval. Those are strong future
neural comparators, but a set of token/meta-token vectors plus MaxSim is still
not the same object as the explicit `plane ⊗ role ⊗ feature` binding used
here. Their reported model-scale results cannot be transferred to this small,
offline signed-hash construct without a new frozen model and compute budget.

Scalable late interaction also has stronger contemporary controls than an
exhaustive MaxSim loop. [MUVERA](https://arxiv.org/abs/2405.19504) constructs
asymmetric fixed-dimensional query/document encodings whose dot product
approximates multi-vector similarity; its June-2026 revision corrects the
published dimension bound. A June-2026 preprint proves a representation-size
separation between nonlinear Chamfer/MaxSim multi-vector scores and
single-vector inner products on worst-case datasets
([Jayaram, 2026](https://arxiv.org/abs/2606.23475)). That separation concerns
the nonlinear secondary arm, not the primary linear separable contraction,
which has the exact flattened-vector reduction above.

## 3. CP factors here are exact storage, not a learned KGE

Canonical Polyadic decomposition represents a third-order tensor as

\[
X=\sum_{k=1}^{R}a_k\otimes b_k\otimes c_k.
\]

For learned knowledge-base completion, a global fact tensor
\(X\in\mathbb R^{N\times |\mathcal R|\times N}\) yields the CP score

\[
s(h,r,t)=\sum_{k=1}^{R}A_{hk}B_{rk}C_{tk}.
\]

This formulation and the material importance of reciprocal predicates and
optimization choices are documented by [Lacroix, Usunier, and Obozinski,
2018](https://proceedings.mlr.press/v80/lacroix18a/lacroix18a.pdf).

The experiment's CP representation is different. Every known binding
\(w_i p_i\otimes r_i\otimes f_i\) is already a rank-one CP term. Storing those
terms exactly introduces no latent fact, training objective, negative sample,
or inferred edge. The CP representation must reconstruct the same
\(4\times4\times32\) tensor within `1e-10`; it is not a separate retrieval arm
and cannot receive a separate quality claim.

Other tensorized KGE scores clarify what is deliberately absent:

- RESCAL uses \(X_r\approx AR_rA^\top\) and
  \(s(h,r,t)=h^\top R_rt\), allowing directed interactions at
  \(O(d^2)\) relation cost. [Nickel, Tresp, and Kriegel,
  2011](https://icml.cc/2011/papers/438_icmlpaper.pdf)
- DistMult is a diagonal/CP restriction
  \(s=\sum_k h_kr_kt_k\); it is cheap but symmetric in head and tail.
- ComplEx uses
  \(s=\operatorname{Re}\sum_k h_kr_k\overline{t_k}\), retaining linear
  complexity while representing symmetric and antisymmetric relations.
  [Trouillon et al.,
  2016](https://proceedings.mlr.press/v48/trouillon16.pdf)
- TuckER shares a core tensor:
  \(s=W\times_1h\times_2r\times_3t\). It can be viewed as a pool of
  prototype relation matrices shared across relations. [Balazevic, Allen, and
  Hospedales, 2019](https://aclanthology.org/D19-1522.pdf)
- LowFER factorizes the shared bilinear interaction as
  \(g(h,r)=\operatorname{SumPool}((U^\top h)\odot(V^\top r),k)\), followed by
  \(g(h,r)^\top t\). [Amin et al.,
  2020](https://proceedings.mlr.press/v119/amin20a/amin20a.pdf)

A learned KGE would answer a different question: which typed graph edge is
plausible? It would not directly answer which revision-bound artifact is
semantically relevant to a text query. It would also introduce a training
corpus, optimizer, negative-sampling policy, transductive entity table, and
link-prediction evaluator that the frozen packet neither specifies nor
authorizes. Therefore this implementation makes no learned-KGE claim.

### What a later KGE experiment would require

A separately frozen work packet would need at least:

- revision-pinned, typed triples and an explicit proposal-only authority
  boundary;
- a train/validation/test split made **before** reciprocal-edge augmentation,
  so a held-out \((h,r,t)\) cannot leak through \((t,r^{-1},h)\);
- type-constrained negative corruptions and filtered evaluation against every
  known positive;
- equal-parameter/equal-step DistMult, ComplEx, RESCAL, and TuckER baselines,
  with LowFER rank sweeps only if core cost is a measured bottleneck;
- 5--10 frozen seeds, filtered MRR/Hits@k, cost receipts, and independently
  verified precision@k for emitted proposals;
- endpoint/label rewiring controls that preserve graph marginals;
- an explicit transductive protocol, or a frozen node-feature encoder and a
  feature-only bilinear baseline for unseen repositories.

Beating symmetric DistMult alone would not support a tensorized graph claim;
ComplEx is the necessary inexpensive asymmetric comparator for directed code
relations.

## 4. TT here is exact conversion, not evidence of useful compression

Tensor Train represents a \(d\)-mode tensor with chained cores:

\[
X(i_1,\ldots,i_d)=G_1(i_1)G_2(i_2)\cdots G_d(i_d),
\]

where \(G_k(i_k)\in\mathbb R^{r_{k-1}\times r_k}\) and
\(r_0=r_d=1\). Its storage is

\[
\sum_{k=1}^{d}n_k r_{k-1}r_k,
\]

approximately \(O(dnr^2)\) for uniform sizes/ranks. TT-SVD obtains cores by
sequentially reshaping unfoldings and applying truncated SVD. These definitions,
the algorithm, and its approximation bound come from [Oseledets,
2011](https://epubs.siam.org/doi/10.1137/090752286). NumPy provides the required
reference operation in
[`numpy.linalg.svd`](https://numpy.org/doc/stable/reference/generated/numpy.linalg.svd.html).

An exact rank-\(R\) CP tensor

\[
X=\sum_{l=1}^{R}a_l\otimes b_l\otimes c_l
\]

has a direct three-core TT representation with ranks no greater than \(R\):

\[
G_1(1,i_1,l)=a_l(i_1),\qquad
G_2(l,i_2,l')=\delta_{ll'}b_l(i_2),\qquad
G_3(l,i_3,1)=c_l(i_3),
\]

with the CP weight placed deterministically in one core. That direct routing is
used when it reproduces every canonical binary64 coordinate exactly. If
placing `weight * plane` in the first core would round away a finite
cancellation residual, overflow, or underflow before later amplification, the
implementation first accumulates the CP coordinate from the exact rational
values of the binary64 factors and emits a deterministic identity-routing TT.
There is still only one final binary64 rounding per coordinate. This is the
selected lossless CP-to-TT conversion relative to the experiment's canonical
binary64 materialization; it is useful for testing serialization, equivalence,
and contraction code paths without fitting an approximation.

It is **not** evidence that TT compression helps this workload:

- the tensor is only `4 x 4 x 32`, so 512 dense float64 values may be smaller
  than TT cores plus shapes and metadata;
- the exact construction may use a non-minimal rank equal to the number of
  binding terms;
- TT rank depends on mode order; `plane -> role -> feature` is a representation
  choice, not a discovered semantic law;
- a dense TT-SVD would first materialize the object it is intended to compress;
- equal reconstruction says nothing about canonical bytes, build time, or
  query latency.

Accordingly, dense, CP, and TT are alternative exact storage/materialization
forms of the same arm. A useful-compression claim is killed unless measured
bytes and latency improve the quality/cost frontier without changing scores.
A later approximate-TT experiment would require a frozen error tolerance,
mode-order sweep declared before results, dense and sparse construction costs,
score error, top-k overlap, retrieval-metric deltas, and an explicit memory
receipt. It would be most plausible only for a genuinely high-order tensor with
measured low unfolding ranks, not merely this three-axis tensor.

## 5. Why this implementation choice is the narrowest valid test

The implementation selects factored TPR plus structured contraction because:

1. the artifact encoder naturally emits a sum of known rank-one
   plane/role/feature bindings;
2. the factor formula computes the frozen separable kernel exactly and remains
   checkable against a 512-scalar dense reference;
3. flattened cosine, identity contraction, and structured contraction can all
   consume the exact same `Candidate.text()` bytes and tensor;
4. the synthetic construct can prove that role/plane binding survives without
   being misreported as a real-world effect;
5. no optimizer, model download, graph authority, or production store is
   needed.

MaxSim remains secondary because it tests a different nonlinear aggregation
and has separate length/storage confounds. CP and TT are implemented exactly
because they fall out of the binding construction and enable strong
equivalence/persistence tests. They are not learned factorization claims.
Tucker/KGE training and approximate TT would add new hypotheses and budgets and
therefore require later, separately frozen experiments.

This choice is thus the narrowest test of a named plane/role prior, not a
complete implementation of every object called a “tensor embedding” and not a
test of tensor-versus-vector representation classes.

## 6. Falsifiers and interpretation rules

The experiment should be considered wrong, uninformative, or negative under
the following conditions.

### Algebra and representation

- Dense, exact CP, and exact TT materializations differ by more than `1e-10`
  on any of the 100 seeded tensors.
- Identity contraction differs from flattened cosine by more than `1e-10`.
- Canonical bytes or digests change across repeated processes for the same
  frozen input and seed.
- A malformed rank, non-finite value, stale spec ID, changed kernel, or mutated
  factor is accepted.

### Structural causality

- The frozen role-binding construct cannot distinguish its bag-equivalent
  decoy under structured contraction.
- Disrupting plane or role assignments while preserving feature values and
  label counts leaves real rankings unchanged.
- The uniform all-to-all kernel performs equivalently to the named kernel.
- Any apparent effect is reproduced by a simpler fixed plane/role prior.

A permutation control must actually break semantic alignment. Applying the
same global permutation to query axes, document axes, and both sides of a
kernel is only a coordinate renaming and is mathematically invariant. The
valid control keeps the frozen kernel coordinates fixed while permuting the
artifact/query label assignments (or otherwise mismatching the bindings), with
the permutation recorded before scores are inspected.

### Real retrieval and budget

- No complete current-`/2`, externally anchored real-data campaign exists yet;
  current outputs are diagnostic/structural only and carry
  `NO_SCIENTIFIC_VERDICT`.
- Structured contraction fails to beat flattened cosine on held-out real data
  under identical 512-scalar and input-byte budgets.
- Its paired interval crosses zero; that result is inconclusive, not
  superiority.
- A gain disappears against BM25, path lexical, recency, available s11 fusion,
  or scrubbed queries.
- Five hash seeds show that collisions or one favorable seed explain the
  result.
- Extra fibers, source bytes, stored scalars, post-result tuning, or candidate
  differences explain a MaxSim or structured-contraction gain.
- CP/TT worsens canonical bytes or query cost, or results fail to transfer to
  a second revision-pinned repository.

Every arm, per-case result, seed, malformed input, failed run, negative result,
and the 10,000-resample paired interval must be retained. A synthetic success
establishes construct validity only; it does not override a real-data loss.

## 7. Honest limitations of the frozen design

1. **The filler is lexical, not a learned semantic embedding.** A 32-dimensional
   signed-hash subword vector tests binding geometry under severe collisions.
   It cannot establish that neural tensor embeddings outperform neural vector
   embeddings. The five frozen hash seeds measure sensitivity but do not
   remove this limitation.
2. **The kernel contains a hand-specified prior.** With the plane-unspecified
   unit query \((1/2,1/2,1/2,1/2)\), the frozen plane kernel has unequal column
   sums: `2.5`, `2.0`, `2.25`, `2.25`. It therefore induces different weights
   for code, type, data, and knowledge documents even before content evidence.
   A gain may be a useful frozen prior, but must not be described as emergent
   tensor semantics. Identity, permutation, uniform-kernel, recency, and
   simpler-prior comparisons are essential to interpretation.
3. **The role kernel is also prior knowledge.** Its off-diagonal values declare
   compatibility in advance. The experiment tests that declaration; it does
   not learn or independently verify those relationships.
4. **Global L2 and operator normalization do not create information.** They
   control scale. Under a fixed kernel they generally cannot explain
   within-arm ranking differences, but zero tensors and numerical edge cases
   still require explicit refusal behavior.
5. **Exact factorization is not necessarily compression.** CP term count can
   exceed minimal rank, and TT metadata/cores may exceed the 4 KiB dense
   float64 payload. Only canonical byte and latency measurements can support a
   storage claim.
6. **MaxSim is length-sensitive.** More document fibers offer more chances for
   a large maximum. Fiber and byte budgets must be asserted, and mean/sum or
   length effects reported rather than hidden.
7. **The experiment is revision-bound and proposal-only.** It says nothing
   about automatic graph truth, cross-revision stability, online index
   mutation, policy, evaluation authority, or promotion.
8. **The frozen unstructured-query adapter duplicates lexical tokens into the
   `symbol` and `content` roles.** This is a declared heuristic, not an
   observed semantic parse, and it can amplify the hand-written role kernel.
   A later adapter must compare content-only queries and syntax-derived symbol
   queries under a newly frozen spec; the present smoke result must not be
   retroactively re-encoded.
9. **The primary score is vectorizable.** Its tensor form records axis
   structure and enables factored execution, but the fixed linear contraction
   is exactly a flattened bilinear vector score. Only the nonlinear Mean-MaxSim
   arm escapes that exact reduction, and it tests a different hypothesis.

These limitations are part of the result. If the primary comparison is
negative, the correct output is retained negative evidence and no production
integration proposal. Until the real baseline campaign and external trust
anchors exist, even a positive diagnostic remains `NO_SCIENTIFIC_VERDICT`.
