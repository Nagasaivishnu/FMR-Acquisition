import pandas as pd
import numpy as np
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt

def derivative_lorentzian(x, x0, w, A):
    """
    Derivative of Lorentzian function.
    L'(x) = -2*A*w^2*(x - x0) / ((x - x0)^2 + w^2)^2
    """
    return -2 * A * w**2 * (x - x0) / ((x - x0)**2 + w**2)**2

def multi_derivative_lorentzian(x, *params):
    """
    Sum of multiple derivative Lorentzian peaks.
    params: [x0_1, w_1, A_1, x0_2, w_2, A_2, ...]
    """
    num_peaks = len(params) // 3
    result = np.zeros_like(x)
    for i in range(num_peaks):
        x0 = params[3*i]
        w = params[3*i + 1]
        A = params[3*i + 2]
        result += derivative_lorentzian(x, x0, w, A)
    return result

def fit_lorentzian_peaks(csv_file, num_peaks, x_column='field', y_column='signal'):
    """
    Fit multiple derivative Lorentzian peaks to data from CSV.

    Parameters:
    csv_file (str): Path to the CSV file
    num_peaks (int): Number of Lorentzian peaks to fit
    x_column (str): Name of the x-axis column (default 'field')
    y_column (str): Name of the y-axis column (default 'signal')

    Returns:
    dict: Fitted parameters and fit quality
    """
    # Read the CSV file
    df = pd.read_csv(csv_file)
    x_data = df[x_column].values
    y_data = df[y_column].values

    # Initial guesses for parameters
    # Assume peaks are roughly evenly spaced
    x_min, x_max = np.min(x_data), np.max(x_data)
    x_range = x_max - x_min
    initial_x0 = np.linspace(x_min + x_range/4, x_max - x_range/4, num_peaks)
    initial_w = np.full(num_peaks, x_range / (4 * num_peaks))  # Width guess
    initial_A = np.full(num_peaks, np.max(np.abs(y_data)) / num_peaks)  # Amplitude guess

    initial_params = []
    for i in range(num_peaks):
        initial_params.extend([initial_x0[i], initial_w[i], initial_A[i]])

    # Perform the fit
    try:
        popt, pcov = curve_fit(multi_derivative_lorentzian, x_data, y_data, p0=initial_params)
    except Exception as e:
        print(f"Fit failed: {e}")
        return None

    # Calculate fitted curve
    y_fit = multi_derivative_lorentzian(x_data, *popt)

    # Calculate R-squared
    ss_res = np.sum((y_data - y_fit)**2)
    ss_tot = np.sum((y_data - np.mean(y_data))**2)
    r_squared = 1 - (ss_res / ss_tot)

    # Organize results
    fitted_params = {}
    for i in range(num_peaks):
        fitted_params[f'Peak_{i+1}'] = {
            'x0': popt[3*i],
            'w': popt[3*i + 1],
            'A': popt[3*i + 2]
        }

    results = {
        'fitted_params': fitted_params,
        'r_squared': r_squared,
        'popt': popt,
        'pcov': pcov,
        'x_data': x_data,
        'y_data': y_data,
        'y_fit': y_fit
    }

    return results

def plot_fit(results, csv_file):
    """
    Plot the original data and the fitted curve.
    """
    x_data = results['x_data']
    y_data = results['y_data']
    y_fit = results['y_fit']

    plt.figure(figsize=(10, 6))
    plt.plot(x_data, y_data, 'b-', label='Original Data', alpha=0.7)
    plt.plot(x_data, y_fit, 'r-', label='Fitted Curve', linewidth=2)
    plt.xlabel('Field')
    plt.ylabel('Signal')
    plt.title(f'FMR Data Fit - {csv_file}')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.show()

if __name__ == "__main__":
    # Get user input
    csv_file = r"C:\Users\Simulation\Documents\Test\FMR\zhehai_Co_Dots_On_PY_Antidots_complete\zhehai_Co_Dots_On_PY_Antidots_complete_100uV_FMR_mmWave7.0GHz_power0dBm_lockin_amp4V_freq_113.52_filter_18.csv"
    try:
        num_peaks = int(input("Enter the number of Lorentzian peaks to fit: "))
    except ValueError:
        print("Invalid number of peaks. Please enter an integer.")
        exit(1)

    # Assume column names - you may need to adjust these
    y_column = 'voltageX'
    x_column = 'field'

    # Perform the fit
    results = fit_lorentzian_peaks(csv_file, num_peaks, x_column, y_column)

    if results:
        print("Fit successful!")
        print(f"R-squared: {results['r_squared']:.4f}")
        print("\nFitted Parameters:")
        for peak, params in results['fitted_params'].items():
            print(f"{peak}: x0={params['x0']:.4f}, w={params['w']:.4f}, A={params['A']:.4f}")

        # Plot the results
        plot_fit(results, csv_file)
    else:
        print("Fit failed. Please check your data and try again.")