import numpy as np
import matplotlib.pyplot as plt

# ==========================================================
# Plot settings (EDIT THESE)
# ==========================================================

legend_labels = [
    "Co Wire on Py Antidot Peak 1",
    "Co Wire on Py Antidot Peak 2",
    "Co Dot On Py Wire",
    "Co Dot on Py Antidot",
]

# ----------------------------------------------------------
# Poster-friendly color scheme
# ----------------------------------------------------------

colors = [
    "crimson",   # Co Wire on Py Antidot Peak 1
    "crimson",   # Co Wire on Py Antidot Peak 2

    "black",     # Co Dot On Py Wire

    "royalblue",       # Co Dot on Py Antidot
]

# ----------------------------------------------------------
# Line styles
# Peak 1 -> Solid
# Peak 2 -> Dotted
# ----------------------------------------------------------

line_styles = [
    "-",      # Peak 1
    ":",      # Peak 2
    "-",      # Single peak
    "-",      # Single peak
]

line_width = 3.0

# ==========================================================
# Magnetic field range (Tesla)
# ==========================================================

H = np.linspace(0.0, 0.2, 1000)

# ==========================================================
# Models
# ==========================================================

def kittel(H, gamma, Meff, Hk):
    """
    Kittel equation

    f = gamma * sqrt((H + Hk) * (H + Hk + Meff))
    """
    inside = (H + Hk) * (H + Hk + Meff)
    inside = np.where(inside > 0, inside, np.nan)
    return gamma * np.sqrt(inside)


def sqrt_model(H, A, B):
    """
    Generic square-root model

    f = A * sqrt(H + B)
    """
    inside = H + B
    inside = np.where(inside > 0, inside, np.nan)
    return A * np.sqrt(inside)

# ==========================================================
# Calculate curves
# ==========================================================

# ----------------------------------------------------------
# Co Wire on Py Antidot
# ----------------------------------------------------------

f1 = sqrt_model(
    H,
    A=31.757,
    B=0.008784,
)

f2 = sqrt_model(
    H,
    A=28.016,
    B=-0.0063443,
)

# ----------------------------------------------------------
# Py Wire + Co Wire
# ----------------------------------------------------------

f3 = kittel(
    H,
    gamma=33.002,
    Meff=0.43791,
    Hk=-0.016693,
)

# ----------------------------------------------------------
# Co Dot on Py Antidot
# ----------------------------------------------------------

f4 = kittel(
    H,
    gamma=33.621,
    Meff=0.53288,
    Hk=-0.0023694,
)

curves = [
    f1,
    f2,
    f3,
    f4,
]

# ==========================================================
# Plot
# ==========================================================

plt.figure(figsize=(7.5, 5.5))

for curve, color, style, label in zip(
    curves,
    colors,
    line_styles,
    legend_labels,
):
    plt.plot(
        H,
        curve,
        color=color,
        linestyle=style,
        linewidth=line_width,
        label=label,
    )

# ==========================================================
# Axis formatting
# ==========================================================

plt.xlim(0.0, 0.2)
plt.ylim(2.0, 10.0)

plt.xlabel("Magnetic Field, H (T)", fontsize=15)
plt.ylabel("Frequency (GHz)", fontsize=15)

plt.xticks(np.arange(0.0, 0.201, 0.05), fontsize=13)
plt.yticks(np.arange(2, 10.1, 1), fontsize=13)

plt.legend(
    fontsize=12,
    frameon=False,
    loc="best",
)

plt.grid(False)

plt.tight_layout()

plt.show()