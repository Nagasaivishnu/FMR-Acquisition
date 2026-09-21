import numpy as np
import matplotlib.pyplot as plt

# ==========================================================
# Plot settings (EDIT THESE)
# ==========================================================

legend_labels = [
    "Py Antidot Peak 1",
    "Py Antidot Peak 2",
    "Co Dot",
    "Co Dot on Py Antidot",
]

# ----------------------------------------------------------
# Same line style for same sample
# ----------------------------------------------------------

line_styles = [
    "-",     # Py Antidot Peak 1
    "-",     # Py Antidot Peak 2
    ":",     # Co Dot
    "--",    # Co Dot on Py Antidot
]

# Peak 1 thicker than Peak 2
line_widths = [
    2.8,
    1.6,
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
# Py Antidot
# ----------------------------------------------------------

f1 = kittel(
    H,
    gamma=33.915,
    Meff=0.57493,
    Hk=0.011619,
)

f2 = kittel(
    H,
    gamma=33.742,
    Meff=0.51284,
    Hk=0.0027117,
)

# ----------------------------------------------------------
# Co Dot
# ----------------------------------------------------------

f3 = kittel(
    H,
    gamma=45.116,
    Meff=0.51187,
    Hk=-0.018926,
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
