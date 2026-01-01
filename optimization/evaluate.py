import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

graph = True
df = None

# csv = "Jan thru Feb 2024.csv"
# csv = "Mar thru Apr 2024.csv"
# csv = "May thru June 2024.csv"
# csv = "July thru Aug 2024.csv"
# csv = "Sep thru Oct 2024.csv"
# csv = "Nov thru Dec 2024.csv"

# csv = "Jan thru Feb 2025.csv"
# csv = "Mar thru Apr 2025.csv"
# csv = "May thru June 2025.csv"
# csv = "Jul thru Aug 2025.csv"

class OptimizationEvaluation:

    def __init__(self):
        self.df = None

    def loadCSV(self, path: str = csv) -> pd.DataFrame:
    # def loadCSV(self, path: str = "testset.csv") -> pd.DataFrame:
        """Load the CSV into the global DataFrame and coerce numeric columns."""
        df = None
        filepath = Path(path)
        if not filepath.exists():
            raise FileNotFoundError(f"CSV file not found: {filepath}")
        df = pd.read_csv(filepath)
        # Coerce relevant numeric columns to numeric types
        for col in ("Net Profit", "Take Profit ATR Distance", "Stop Loss ATR Distance"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        self.df = df
        return df


    def calcPercentProfitable(self) -> float:
        """Calculate and print percentage of rows with positive Net Profit."""
        if self.df is None:
            raise RuntimeError("Data not loaded. Call loadCSV() first.")
        valid = self.df["Net Profit"].dropna()

        # Calculate total number of positive profits
        num_positive = (valid > 0).sum()
        print(f"Profitable trades: {num_positive}")

        pct = (valid > 0).mean() * 100
        print(f"Percent profitable: {pct:.2f}%")
        return pct


    def calcMeanProfit(self) -> float:
        """Calculate and print mean Net Profit."""
        if self.df is None:
            raise RuntimeError("Data not loaded. Call loadCSV() first.")
        mean = self.df["Net Profit"].mean()
        print(f"Mean Net Profit: {mean:.4f}")
        return mean


    def calcProfitStdDev(self) -> float:
        """Calculate and print standard deviation of Net Profit."""
        if self.df is None:
            raise RuntimeError("Data not loaded. Call loadCSV() first.")
        std = self.df["Net Profit"].std()
        print(f"Net Profit std dev: {std:.4f}")
        return std


    def findMaxMinProfit(self) -> dict:
        """Find and print max, min and range of Net Profit."""
        if self.df is None:
            raise RuntimeError("Data not loaded. Call loadCSV() first.")
        s = self.df["Net Profit"].dropna()
        maxi = s.max()
        mini = s.min()
        rng = maxi - mini
        print(f"Max Net Profit: {maxi:.4f}")
        print(f"Min Net Profit: {mini:.4f}")
        print(f"Range: {rng:.4f}")
        return {"max": maxi, "min": mini, "range": rng}


    def graphProfit(self, outpath: str = "profit_hist.png") -> str:
        """Create and save a histogram of Net Profit. Returns output path."""
        if self.df is None:
            raise RuntimeError("Data not loaded. Call loadCSV() first.")
        # Prefer a 3D scatter: X = Take Profit ATR Distance, Y = Stop Loss ATR Distance, Z = Net Profit
        required = ["Take Profit ATR Distance", "Stop Loss ATR Distance", "Net Profit"]
        for c in required:
            if c not in self.df.columns:
                raise RuntimeError(f"Required column missing for 3D plot: {c}")

        data = self.df[required].dropna()
        if data.empty:
            raise RuntimeError("No valid rows for 3D plotting after dropping NaNs.")

        x = pd.to_numeric(data["Take Profit ATR Distance"], errors="coerce")
        y = pd.to_numeric(data["Stop Loss ATR Distance"], errors="coerce")
        z = pd.to_numeric(data["Net Profit"], errors="coerce")

        fig = plt.figure(figsize=(9, 6))
        ax = fig.add_subplot(111, projection="3d")
        p = ax.scatter(x, y, z, c=z, cmap="viridis", s=40, edgecolor="k", depthshade=True)
        ax.set_xlabel("Take Profit ATR Distance")
        ax.set_ylabel("Stop Loss ATR Distance")
        ax.set_zlabel("Net Profit")
        ax.set_title("Net Profit vs Take/Stop ATR Distances")
        fig.colorbar(p, ax=ax, shrink=0.6, label="Net Profit")
        plt.tight_layout()
        plt.savefig(outpath)
        plt.close()
        print(f"Saved 3D plot to: {outpath}")
        return outpath


    def evaluate(self):
        self.loadCSV()
        self.calcPercentProfitable()
        self.calcMeanProfit()
        self.calcProfitStdDev()
        self.findMaxMinProfit()  # Also give range
        if graph:
            self.graphProfit()

def main():
    oe = OptimizationEvaluation()
    oe.evaluate()


if __name__ == "__main__":
    main()