import numpy as np
import matplotlib.pyplot as plt

# ==========================================================
# Plot settings (EDIT THESE)
# ==========================================================

legend_labels = [
    "Py Wire",
    "Co Wire",
]

# ----------------------------------------------------------
# Line styles (one style per sample)
# ----------------------------------------------------------

line_styles = [
    "-",     # Py Wire
    "--",    # Co Wire
]

line_widths = [
    2.8,
    2.8,
]

# ==========================================================
# Magnetic field range (Tesla)
# ==========================================================

H = np.linspace(0.0, 0.2, 1000)

# ==========================================================
# Kittel model
# ==========================================================

def kittel(H, gamma, Meff, Hk):
    """
    f = gamma * sqrt((H + Hk) * (H + Hk + Meff))

    gamma : GHz/T
    H      : Tesla
    Meff   : Tesla
    Hk     : Tesla

    Returns frequency in GHz.
    """
    inside = (H + Hk) * (H + Hk + Meff)

    inside = np.where(inside > 0, inside, np.nan)

    return gamma * np.sqrt(inside)

# ==========================================================
# Calculate curves
# ==========================================================

# ----------------------------------------------------------
# Py Wire
# ----------------------------------------------------------

f1 = kittel(
    H,
    gamma=32.083,
    Meff=0.42649,
    Hk=-0.022807,
)

# ----------------------------------------------------------
# Co Wire
# ----------------------------------------------------------

f2 = kittel(
    H,
    gamma=42.006,
    Meff=0.63769,
    Hk=-0.017187,
)

curves = [
    f1,
    f2,
]

# ==========================================================
# Plot
# ==========================================================

plt.figure(figsize=(7.2, 5.5))

for curve, style, width, label in zip(
    curves,
    line_styles,
    line_widths,
    legend_labels,
):
    plt.plot(
        H,
        curve,
        color="black",
        linestyle=style,
        linewidth=width,
        label=label,
    )

# ==========================================================
# Axis formatting
# ==========================================================

plt.xlim(0.0, 0.2)
plt.ylim(2.0, 10.0)

plt.xlabel("Magnetic Field, H (T)", fontsize=14)
plt.ylabel("Frequency (GHz)", fontsize=14)

plt.xticks(np.arange(0.0, 0.201, 0.05), fontsize=12)
plt.yticks(np.arange(2, 10.1, 1), fontsize=12)

plt.legend(
    frameon=False,
    fontsize=11,
    loc="best",
)

plt.grid(False)

plt.tight_layout()

plt.show()