"""Preprocessing pipeline.

Fitted ONLY on training data and persisted together with the model, so
inference-time preprocessing is bit-for-bit identical to training.
Tree ensembles need no scaling; the pipeline's job is median imputation for
robustness against future missing values (the current dataset has none).
"""
import numpy as np


class Preprocessor:
    """Median imputer fitted on the training split. Kept as plain numpy
    (not a sklearn Pipeline) so the persisted artifact is self-describing."""

    def __init__(self, medians=None):
        self.medians = medians  # ndarray of shape (n_features,)
        self.fitted = medians is not None

    def fit(self, X):
        X = np.asarray(X, dtype=np.float64)
        self.medians = np.nanmedian(X, axis=0)
        # A feature that is entirely NaN in training would yield NaN median;
        # fall back to 0 so transform never emits NaN.
        self.medians = np.where(np.isnan(self.medians), 0.0, self.medians)
        self.fitted = True
        return self

    def transform(self, X):
        if not self.fitted:
            raise RuntimeError("Preprocessor.transform called before fit.")
        X = np.asarray(X, dtype=np.float64).copy()
        if X.ndim == 1:
            X = X.reshape(1, -1)
        nan_mask = np.isnan(X)
        if nan_mask.any():
            # Column-wise replacement using broadcast medians.
            indices = np.where(nan_mask)
            X[indices] = np.take(self.medians, indices[1])
        return X

    def fit_transform(self, X):
        return self.fit(X).transform(X)

    def to_dict(self):
        return {"medians": self.medians.tolist()}

    @classmethod
    def from_dict(cls, data):
        return cls(medians=np.asarray(data["medians"], dtype=np.float64))
