import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

shouldPlot = True

def compute_log_returns_cov(prices: pd.DataFrame):
    """
    Computes log returns and covariance matrix for multi-asset daily price data,
    handling missing data via forward-fill and ignoring filled returns in covariance.

    Parameters
    ----------
    prices : pd.DataFrame
        Daily price data. Columns = assets, index = dates.

    Returns
    -------
    log_returns : pd.DataFrame
        Daily log returns with NaNs where returns depend on filled prices.
    cov_matrix : pd.DataFrame
        Covariance matrix computed using only valid (non-filled) returns.
    """
    # Step 1: Track original missing data
    missing_mask = prices.isna()
    
    # Step 2: Forward-fill prices to allow return computation
    prices_filled = prices.ffill()
    
    # Step 3: Compute log returns
    log_returns = np.log(prices_filled / prices_filled.shift(1))

    # For Efficient Frontier of trading Strategies, the strategies will have 0 return when they have exited a trade and not entered another. For this, the 0% return should not be masked.
    
    # Step 4: Mark returns as NaN if they depend on filled prices
    # A return is invalid if either today's or yesterday's price was filled
    invalid_mask = missing_mask | missing_mask.shift(1)
    log_returns = log_returns.mask(invalid_mask)
    
    # Step 5: Compute covariance matrix ignoring invalid returns
    cov_matrix = log_returns.cov()
    
    return log_returns, cov_matrix

def compute_ABC(log_returns: pd.DataFrame, cov_matrix: pd.DataFrame):
    """
    Computes A, B, C, D scalars for the analytical efficient frontier.

    Parameters
    ----------
    log_returns : pd.DataFrame
        Daily log returns (with NaNs for missing/filled values).
    cov_matrix : pd.DataFrame
        Covariance matrix computed from log_returns.

    Returns
    -------
    dict
        Dictionary containing A, B, C, D.
    """
    # Step 1: compute expected returns vector (mean log returns)
    mu = log_returns.mean().values.reshape(-1, 1)  # n x 1
    
    # Step 2: compute inverse covariance matrix a.k.a the precision matrix
    Sigma_inv = np.linalg.inv(cov_matrix.values)
    
    # Step 3: create ones vector
    ones = np.ones((mu.shape[0], 1))
    
    # Step 4: compute scalars
    A = float(ones.T @ Sigma_inv @ ones)
    B = float(ones.T @ Sigma_inv @ mu)
    C = float(mu.T @ Sigma_inv @ mu)
    D = A * C - B**2
    
    return {"A": A, "B": B, "C": C, "D": D, "mu": mu, "Sigma_inv": Sigma_inv}

def compute_efficient_frontier_weights(cov_matrix, ABC: dict, target_returns):
    """
    Computes portfolio weights for each target return along the efficient frontier.

    Parameters
    ----------
    ABC : dict
        Dictionary containing A, B, C, D, mu, Sigma_inv (from compute_ABC)
    target_returns : list or np.array
        List of target portfolio returns.

    Returns
    -------
    weights_df : pd.DataFrame
        Each column corresponds to the weights of a portfolio for a target return.
    port_std : pd.Series
        Standard deviations for each target return
    """
    Sigma_inv = ABC["Sigma_inv"]
    mu = ABC["mu"]
    A, B, C, D = ABC["A"], ABC["B"], ABC["C"], ABC["D"]
    
    weights_list = []
    
    for r in target_returns:
        # Compute weights using the analytical formula
        w_r = Sigma_inv @ ((C - r * B) / D * np.ones_like(mu) + (r * A - B) / D * mu)
        weights_list.append(w_r.flatten())
    
    # Return as DataFrame for readability
    weights_df = pd.DataFrame(
        np.column_stack(weights_list),
        index=[col for col in range(len(mu))],
        columns=[f"r={r:.4f}" for r in target_returns]
    )

    port_variances = np.array([w.T @ cov_matrix.values @ w for w in weights_df.T.values])
    port_std = pd.Series(np.sqrt(port_variances), index=weights_df.columns)
    
    return weights_df, port_std

def compute_global_minimum_variance_portfolio(ABC: dict):
    """
    Computes portfolio weights for each target return along the efficient frontier.

    Parameters
    ----------
    ABC : dict
        Dictionary containing A, B, C, D, mu, Sigma_inv (from compute_ABC)

    Returns
    -------
    w_gmvp : pd.DataFrame
        Weights of the minimum variance portfolio
    sigma_gmvp : Integer
        Standard deviation of the minimum variance portfolio
    """
    Sigma_inv = ABC["Sigma_inv"]
    A = ABC["A"]

    w_gmvp = Sigma_inv @ np.ones((len(Sigma_inv), 1)) / A
    sigma_gmvp = np.sqrt(1 / A)

    return w_gmvp, sigma_gmvp
    

def calculate_efficient_frontier(prices, target_returns):

    log_returns, cov_matrix = compute_log_returns_cov(prices)
    marketComponentsDict = compute_ABC(log_returns, cov_matrix)
    weightsMinRisk, stdMinRisk = compute_global_minimum_variance_portfolio(marketComponentsDict)
    weightsDF, portSTD = compute_efficient_frontier_weights(cov_matrix, marketComponentsDict, target_returns)
    if shouldPlot:
        plot__efficient_frontier(portSTD, target_returns)

def plot__efficient_frontier(port_std, target_returns):
    plt.plot(port_std, target_returns)
    plt.xlabel("Portfolio Std Dev")
    plt.ylabel("Expected Return")
    plt.title("Efficient Frontier")
    plt.show()

# if __name__ == "__main__":
    # Get prices
    # Get target_returns
    # calculate_efficient_frontier(prices, target_returns)