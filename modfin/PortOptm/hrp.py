import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.spatial.distance import squareform
from scipy.cluster.hierarchy import linkage as scipy_linkage, dendrogram

from modfin.Analysis import CovMatrix
from modfin.utils import Resampler, PortfolioMetrics


class HierarchicalRiskParity():
    """
    Hierarchical Risk Parity Portfolio Optimization

    The Hierarchical Risk Parity algorithm, implements the allocation based on the book:

    `De Prado, Marcos Lopez. Advances in financial machine learning. John Wiley & Sons, 2018.` ISBN-10: 1119482089

    Obs.: The algorithm is specifically described in the Chapter 16 of the book.

    Parameters
    ----------

    RiskMetric : :py:class:`str`, optional.
    - ``variance`` : Sample Covariance of the returns of the assets as the risk metric. (Default)
    - ``semivariance`` : Sample Semi-Covariance of the returns of the assets as the risk metric.
    - ``shrinkage`` : Shrinked Covariance as the risk metric.
    - ``letoidwolf`` : Shrinked Covariance by the Letoid-Wolf method as the risk metric.
    - ``oas`` : Shrinked Covariance by the Oracle Approximating method as the risk metric.

    Method : :py:class:`str`, Method of linkage used in the Hierarchical Clustering.
    - ``ward`` : Ward's method.
    - ``single`` : For all points i in cluster u and j in cluster v. This is also known as the Nearest Point Algorithm. `(default method, and the original method mentioned in the book)`.
    - ``median`` : When two clusters s and are t combined into a new cluster u, the average of centroids s and t give the new centroid . This is also known as the WPGMC algorithm.
    - ``average`` : For all points i and j where |u| and |v| are the cardinalities of clusters  and , respectively. This is also called the UPGMA algorithm.
    - ``complete`` : For all points i in cluster u and j in cluster v. This is also known by the Farthest Point Algorithm or Voor Hees Algorithm.
    - ``weighted`` : Where cluster u was formed with cluster s and t and v is a remaining cluster in the forest (also called WPGMA).
    - ``centroid`` : For all points i in cluster u and j in cluster v. This is also known as the UPGMC algorithm.

    For more information about the linkage methods, see:
        Scipy : https://docs.scipy.org/doc/scipy/reference/generated/scipy.cluster.hierarchy.linkage.html


    Functions
    ---------
    - optimize : Calculate the optimal portfolio allocation using the Hierarchical Risk Parity algorithm.

    - plot : Plot the algorithm decision tree.
    """

    def __init__(self, RiskMetrics: str = "Variance", Method: str = 'Single'):

        self.clusters = None

        # Define the metric to be employed as risk
        if RiskMetrics.lower() not in ["variance", "semivariance", "shrinkage", "letoidwolf", "oas"]:
            raise ValueError(
                "RiskMetrics must be one of the following: 'Variance', 'Semivariance', 'Shrinkage', 'LetoidWolf' or 'OAS'")

        self._RiskMetrics = RiskMetrics.lower()

        # Define the method of linkage to be used
        if Method.lower() not in ["ward", "single", "average", "complete", "median", "weighted", "centroid"]:
            raise ValueError(
                "Method must be one of the following: 'Ward', 'Single', 'Average', 'Complete', 'Median', 'Weighted' or 'Centroid'")

        self._Method = Method.lower()

    def _getQuasiDiag(cluster, num_assets, curr_index):
        # Sort clustered items by distance
        if curr_index < num_assets:
            return [curr_index]
        left = int(cluster[curr_index - num_assets, 0])
        right = int(cluster[curr_index - num_assets, 1])
        return (HierarchicalRiskParity._getQuasiDiag(cluster, num_assets, left) + HierarchicalRiskParity._getQuasiDiag(cluster, num_assets, right))

    def _getClusterVar(covariance, cluster_indices):
        # Calculate the variance of the clusters
        cluster_covariance = covariance.iloc[cluster_indices, cluster_indices]
        parity_w = HierarchicalRiskParity._getIVP(cluster_covariance)
        cluster_variance = PortfolioMetrics.ExpectedVariance(
            CovarianceMatrix=cluster_covariance, Weights=parity_w)
        return cluster_variance

    def _getIVP(cov):
        ivp = 1 / np.diag(cov.values)
        ivp = ivp * (1 / np.sum(ivp))
        return ivp

    def _getRecBipart(covariance_matrix, assets, ordered_indices):
        # Compute HRP allocation
        weights = pd.Series(1, index=ordered_indices)

        # Initialize all clusters with the same alpha score
        clustered_alphas = [ordered_indices]

        while clustered_alphas:
            # bi-section of cluster
            clustered_alphas = [cluster[start:end]
                                for cluster in clustered_alphas
                                for start, end in ((0, len(cluster) // 2), (len(cluster) // 2, len(cluster)))
                                if len(cluster) > 1]

            for subcluster in range(0, len(clustered_alphas), 2):
                left_cluster = clustered_alphas[subcluster]
                right_cluster = clustered_alphas[subcluster + 1]
                left_cluster_variance = HierarchicalRiskParity._getClusterVar(
                    covariance_matrix, left_cluster)
                right_cluster_variance = HierarchicalRiskParity._getClusterVar(
                    covariance_matrix, right_cluster)
                alloc_factor = 1 - left_cluster_variance / \
                    (left_cluster_variance + right_cluster_variance)

                # Apply the allocation factor to the left and right cluster
                weights[left_cluster] *= alloc_factor
                weights[right_cluster] *= 1 - alloc_factor

        # Apply the resulting weights to the assets
        weights.index = assets[ordered_indices]
        return weights

    def optimize(self, AssetPrices: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate the optimal portfolio allocation using the Hierarchical Risk Parity algorithm.

        Parameters
        ----------
        AssetPrices : py:class:`pandas.DataFrame` with the daily asset prices

        Returns
        -------
        Portifolio : :py:class:`pandas.DataFrame` with the weights of the portfolio
        """

        # Check if the asset prices are valid
        if AssetPrices is not None:
            if not isinstance(AssetPrices, pd.DataFrame):
                raise ValueError(
                    "Asset Prices must be a Pandas DataFrame!")
            if not isinstance(AssetPrices.index, pd.DatetimeIndex):
                raise ValueError(
                    "Asset Prices must be a Pandas DataFrame index by datetime!")

        # Calculate asset returns
        asset_returns = AssetPrices.pct_change()
        asset_returns = asset_returns.dropna(
            axis="index", how='all').dropna(axis="columns", how='all')
        asset_names = asset_returns.columns

        if self._RiskMetrics == "variance":
            risk_matrix = CovMatrix.Sample(asset_returns)

        elif self._RiskMetrics == "semivariance":
            risk_matrix = CovMatrix.SampleSemi(asset_returns)

        elif self._RiskMetrics == "shrinkage":
            risk_matrix = CovMatrix.BasicShrinkage(asset_returns)

        elif self._RiskMetrics == "letoidwolf":
            risk_matrix = CovMatrix.LedoitWolf(asset_returns)

        elif self._RiskMetrics == "oas":
            risk_matrix = CovMatrix.Oracle(asset_returns)

        if not isinstance(risk_matrix, pd.DataFrame):
            risk_matrix = pd.DataFrame(
                risk_matrix, index=asset_names, columns=asset_names)

        # Calculate the correlation matrix from the risk matrix
        correlation_matrix = Resampler.Cov2Corr(risk_matrix)

        # Calculate the euclidian distance between all assets correlations
        distance_matrix = np.sqrt((1 - correlation_matrix).round(10) / 2)

        # Tree clustering the distance matrix
        clusters = scipy_linkage(squareform(
            distance_matrix), method=self._Method)
        self.clusters = clusters

        # Quasi diagnalization of the tree clusters
        num_assets = len(asset_names)
        ordered_indices = HierarchicalRiskParity._getQuasiDiag(
            clusters, num_assets, (2 * num_assets - 2))

        # Recursive Bisection from ordered asset indices
        Portifolio = HierarchicalRiskParity._getRecBipart(
            covariance_matrix=risk_matrix, assets=asset_names, ordered_indices=ordered_indices)

        # Remove the weights of the assets that are >1-e8.
        Portifolio = Portifolio.round(8)
        Portifolio /= Portifolio.sum()
        Portifolio[Portifolio == 0] = 'nan'
        Portifolio = Portifolio.to_frame().T
        Portifolio = Portifolio[asset_names].dropna(axis="columns")
        return Portifolio

    def plot(self, Size=6):
        """
        Plot the algorithm decision tree.

        Parameters
        ----------
        Size : :py:class:`int`, Size of the figure. The default is 6.

        """
        # Check if clusters is defined
        if self.clusters is None:
            raise ValueError(
                "You must run the Optimize method before plotting")

        # Plot the dendrogram
        fig = plt.figure(num=None, figsize=(1.25 * Size, Size), dpi=80)
        ax1 = fig.add_subplot(111)
        ax1.title.set_text('Hierarchical Risk Parity Dendrogram')
        ax1 = dendrogram(self.clusters, labels=self.asset_names,
                         show_leaf_counts=True)
        plt.grid(False)
        plt.tight_layout()
        plt.show()
