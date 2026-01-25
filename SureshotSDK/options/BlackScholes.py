"""
Black-Scholes Option Pricing Model

This module implements the Black-Scholes-Merton model for pricing European-style options
and calculating option Greeks (sensitivities).

The Black-Scholes model assumes:
1. European-style options (exercise only at expiration)
2. No dividends paid during the option's life
3. Efficient markets (no arbitrage opportunities)
4. Constant risk-free rate and volatility
5. Log-normal distribution of stock prices

Note: For dividend-paying stocks, use the dividend-adjusted model or
subtract present value of dividends from spot price.
"""

import numpy as np
from scipy.stats import norm
from typing import NamedTuple, Literal
from datetime import datetime


class OptionGreeks(NamedTuple):
    """Container for option Greek values"""
    delta: float      # Rate of change of option price with respect to underlying price
    gamma: float      # Rate of change of delta with respect to underlying price
    theta: float      # Rate of change of option price with respect to time (per day)
    vega: float       # Rate of change of option price with respect to volatility (per 1% change)
    rho: float        # Rate of change of option price with respect to risk-free rate


def calculate_d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Calculate d1 parameter for Black-Scholes formula

    Args:
        S: Current stock price
        K: Strike price
        T: Time to expiration (in years)
        r: Risk-free interest rate (annualized)
        sigma: Volatility (annualized standard deviation)

    Returns:
        d1 value
    """
    if T <= 0:
        raise ValueError("Time to expiration must be positive")
    if sigma <= 0:
        raise ValueError("Volatility must be positive")
    if S <= 0:
        raise ValueError("Stock price must be positive")

    numerator = np.log(S / K) + (r + 0.5 * sigma ** 2) * T
    denominator = sigma * np.sqrt(T)
    return numerator / denominator


def calculate_d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Calculate d2 parameter for Black-Scholes formula

    Args:
        S: Current stock price
        K: Strike price
        T: Time to expiration (in years)
        r: Risk-free interest rate (annualized)
        sigma: Volatility (annualized standard deviation)

    Returns:
        d2 value
    """
    d1 = calculate_d1(S, K, T, r, sigma)
    return d1 - sigma * np.sqrt(T)


def calculate_call_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Calculate European call option price using Black-Scholes formula

    Formula: C = S * N(d1) - K * e^(-rT) * N(d2)

    Where:
        N(x) = Cumulative standard normal distribution function
        d1 = [ln(S/K) + (r + σ²/2)T] / (σ√T)
        d2 = d1 - σ√T

    Args:
        S: Current stock price
        K: Strike price
        T: Time to expiration (in years)
        r: Risk-free interest rate (annualized, e.g., 0.045 for 4.5%)
        sigma: Volatility (annualized, e.g., 0.20 for 20%)

    Returns:
        Call option price
    """
    if T <= 0:
        # At expiration or expired
        return max(0.0, S - K)

    d1 = calculate_d1(S, K, T, r, sigma)
    d2 = calculate_d2(S, K, T, r, sigma)

    call_price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return max(0.0, call_price)


def calculate_put_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Calculate European put option price using Black-Scholes formula

    Formula: P = K * e^(-rT) * N(-d2) - S * N(-d1)

    Or using put-call parity: P = C - S + K * e^(-rT)

    Args:
        S: Current stock price
        K: Strike price
        T: Time to expiration (in years)
        r: Risk-free interest rate (annualized, e.g., 0.045 for 4.5%)
        sigma: Volatility (annualized, e.g., 0.20 for 20%)

    Returns:
        Put option price
    """
    if T <= 0:
        # At expiration or expired
        return max(0.0, K - S)

    d1 = calculate_d1(S, K, T, r, sigma)
    d2 = calculate_d2(S, K, T, r, sigma)

    put_price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return max(0.0, put_price)


def calculate_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: Literal['call', 'put']
) -> OptionGreeks:
    """
    Calculate option Greeks for a given option

    Args:
        S: Current stock price
        K: Strike price
        T: Time to expiration (in years)
        r: Risk-free interest rate (annualized)
        sigma: Volatility (annualized)
        option_type: 'call' or 'put'

    Returns:
        OptionGreeks named tuple with delta, gamma, theta, vega, and rho
    """
    if T <= 0:
        # At expiration
        if option_type == 'call':
            delta = 1.0 if S > K else 0.0
        else:  # put
            delta = -1.0 if S < K else 0.0

        return OptionGreeks(
            delta=delta,
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            rho=0.0
        )

    d1 = calculate_d1(S, K, T, r, sigma)
    d2 = calculate_d2(S, K, T, r, sigma)

    # Delta: ∂V/∂S
    if option_type == 'call':
        delta = norm.cdf(d1)
    else:  # put
        delta = norm.cdf(d1) - 1

    # Gamma: ∂²V/∂S² (same for calls and puts)
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))

    # Vega: ∂V/∂σ (same for calls and puts)
    # Note: Vega is typically expressed per 1% change in volatility
    vega = S * norm.pdf(d1) * np.sqrt(T) / 100

    # Theta: ∂V/∂t (expressed per day)
    if option_type == 'call':
        theta = (
            -S * norm.pdf(d1) * sigma / (2 * np.sqrt(T))
            - r * K * np.exp(-r * T) * norm.cdf(d2)
        ) / 365
    else:  # put
        theta = (
            -S * norm.pdf(d1) * sigma / (2 * np.sqrt(T))
            + r * K * np.exp(-r * T) * norm.cdf(-d2)
        ) / 365

    # Rho: ∂V/∂r (expressed per 1% change in interest rate)
    if option_type == 'call':
        rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100
    else:  # put
        rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100

    return OptionGreeks(
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        rho=rho
    )


def calculate_implied_volatility(
    option_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: Literal['call', 'put'],
    max_iterations: int = 100,
    tolerance: float = 1e-5
) -> float:
    """
    Calculate implied volatility using Newton-Raphson method

    Args:
        option_price: Observed market price of the option
        S: Current stock price
        K: Strike price
        T: Time to expiration (in years)
        r: Risk-free interest rate (annualized)
        option_type: 'call' or 'put'
        max_iterations: Maximum iterations for convergence
        tolerance: Convergence tolerance

    Returns:
        Implied volatility (annualized)

    Raises:
        ValueError: If implied volatility cannot be calculated
    """
    if T <= 0:
        raise ValueError("Cannot calculate implied volatility for expired options")

    # Initial guess: ATM volatility approximation
    sigma = 0.3  # 30% initial guess

    for i in range(max_iterations):
        if option_type == 'call':
            price = calculate_call_price(S, K, T, r, sigma)
        else:
            price = calculate_put_price(S, K, T, r, sigma)

        diff = price - option_price

        if abs(diff) < tolerance:
            return sigma

        # Vega for Newton-Raphson iteration
        vega = S * norm.pdf(calculate_d1(S, K, T, r, sigma)) * np.sqrt(T)

        if vega < 1e-10:
            raise ValueError("Vega too small, cannot calculate implied volatility")

        sigma = sigma - diff / vega

        # Keep sigma positive
        if sigma <= 0:
            sigma = 0.01

    raise ValueError(f"Implied volatility did not converge after {max_iterations} iterations")


def days_to_years(days: int) -> float:
    """
    Convert days to years for time-to-expiration calculation

    Args:
        days: Number of days until expiration

    Returns:
        Time in years
    """
    return days / 365.0


def calculate_time_to_expiration(current_date: datetime, expiration_date: datetime) -> float:
    """
    Calculate time to expiration in years

    Args:
        current_date: Current date
        expiration_date: Option expiration date

    Returns:
        Time to expiration in years
    """
    days = (expiration_date - current_date).days
    return days_to_years(days)


if __name__ == "__main__":
    # Example usage and validation
    print("Black-Scholes Option Pricing Examples\n")

    # Example 1: At-the-money call
    S = 100  # Stock price
    K = 100  # Strike price
    T = 1.0  # 1 year to expiration
    r = 0.045  # 4.5% risk-free rate
    sigma = 0.20  # 20% volatility

    call_price = calculate_call_price(S, K, T, r, sigma)
    put_price = calculate_put_price(S, K, T, r, sigma)

    print(f"ATM Call Price: ${call_price:.2f}")
    print(f"ATM Put Price: ${put_price:.2f}")

    greeks_call = calculate_greeks(S, K, T, r, sigma, 'call')
    print(f"\nCall Greeks:")
    print(f"  Delta: {greeks_call.delta:.4f}")
    print(f"  Gamma: {greeks_call.gamma:.4f}")
    print(f"  Theta: ${greeks_call.theta:.4f} per day")
    print(f"  Vega: ${greeks_call.vega:.4f} per 1% vol change")
    print(f"  Rho: ${greeks_call.rho:.4f} per 1% rate change")

    # Example 2: Out-of-the-money put
    K_otm = 95  # 5% OTM
    put_otm_price = calculate_put_price(S, K_otm, T, r, sigma)
    print(f"\n5% OTM Put Price: ${put_otm_price:.2f}")

    # Example 3: Implied Volatility
    market_price = 8.50
    iv = calculate_implied_volatility(market_price, S, K, T, r, 'call')
    print(f"\nImplied Volatility for ${market_price:.2f} call: {iv*100:.2f}%")
