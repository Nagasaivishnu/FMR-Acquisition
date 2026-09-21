import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.integrate import cumulative_trapezoid
import re
from natsort import natsorted
from scipy.signal import detrend, savgol_filter


def extract_frequency(filename):
    """Extract frequency from filename using regex.
    Example: FMR_mmWave5.0GHz -> 5.0
    """
    match = re.search(r'mmWave([\d.]+)GHz', filename)
    if match:
        return float(match.group(1))
    return None


def transform_voltages(volx, voly):
    """Transform voltage_x and voltage_y based on maximum values."""
    max_x = volx.max()
    max_y = voly.max()
    
    theta = np.atan2(max_y, max_x)
    
    transformed_x = volx * np.cos(theta) + voly * np.sin(theta)
    transformed_y = -volx * np.sin(theta) + voly * np.cos(theta)

    R = np.sqrt(volx**2 + voly**2)
    theta = np.arctan2(voly, volx)
    
    return np.array(transformed_x), np.array(transformed_y), theta, R


def calculate_absorption(H_field, signal):
    """Calculate absorption as integrated signal."""
    H = np.array(H_field)
    signal_array = detrend(np.array(signal) - np.mean(signal))
    #signal_array = detrend(signal_array)  # Remove linear trend if necessary
    smoothed_signal = savgol_filter(signal_array, 21, 3)
    # Cumulative integration of the absorption signal
    absorption = cumulative_trapezoid(smoothed_signal, H, initial=0)
    #absorption = (absorption - np.min(absorption)) / (np.max(absorption) - np.min(absorption))  # Normalize if desired
    
    #return np.exp(np.exp(np.array(absorption)/np.max(absorption)))  # Example: exponential scaling for better visualization
    return np.array(absorption)



def read_and_process_csv_files(directory, background_directory=None):
    """Read all CSV files from directory, process and return absorption data.
    
    Parameters:
    -----------
    directory : str or Path
        Directory containing FMR CSV files
        
    Returns:
    --------
    dict : Dictionary with frequency as key and absorption data as value
    """
    directory = Path(directory)
    background_directory = Path(background_directory) if background_directory else None
    csv_files = sorted(directory.glob("**/*FMR*.csv"))
    bg_csv_files = sorted(background_directory.glob("**/*FMR*.csv")) if background_directory else [] 
    
    if not csv_files:
        print(f"No FMR CSV files found in {directory}")
        return {}
    
    
    results = {}
    freq_to_file = {}
    
    # First pass: collect files and frequencies
    for csv_file in csv_files:
        freq = extract_frequency(csv_file.name)
        if freq is not None:
            freq_to_file[freq] = csv_file
    
    if bg_csv_files is not None:
        bg_freq_to_file = {}
        for bg_csv_file in bg_csv_files:
            freq = extract_frequency(bg_csv_file.name)
            if freq is not None:
                bg_freq_to_file[freq] = bg_csv_file

    # Sort by frequency
    sorted_frequencies = sorted(freq_to_file.keys())#[0:200]
    
    # Process each file
    for freq in sorted_frequencies:
        csv_file = freq_to_file[freq]
        bg_csv_file = bg_freq_to_file.get(freq) if bg_csv_files is not None else None
        print(f"Processing {csv_file.name} (Frequency: {freq} GHz)...")
        print(f"Background file: {bg_csv_file.name if bg_csv_file else 'None'}")
        
        try:
            # Read CSV
            data = pd.read_csv(csv_file)
            bg_data = pd.read_csv(bg_csv_file) if bg_csv_file is not None else None
            
            # Extract columns
            volx = np.array(data['voltageX'])# - np.array(bg_data['voltageX'][:len(data["voltageX"])]) if bg_data is not None else np.array(data['voltageX'])
            voly = np.array(data['voltageY'])# - np.array(bg_data['voltageY'][:len(data["voltageY"])]) if bg_data is not None else np.array(data['voltageY'])
            H_field = np.array(data['field'])
            
            # Transform voltages
            transformed_x, transformed_y, theta, R = transform_voltages(volx, voly)
            bg_transformed_x, bg_transformed_y, bg_theta, bg_R = transform_voltages(np.array(bg_data['voltageX']), np.array(bg_data['voltageY'])) if bg_data is not None else (None, None, None, None)  

            #normalized
            transformed_x = np.abs(transformed_x)/np.max(np.abs(transformed_x))
            transformed_y = np.abs(transformed_y)/np.max(np.abs(transformed_y))

            if bg_R is not None:
                if len(R) > len(bg_R):
                    bg_R = np.pad(bg_R, (0, len(R) - len(bg_R)), mode='edge')  # Pad with last value if bg_R is shorter
                R = np.array(R) - np.array(bg_R[:len(R)]) if bg_R is not None else np.array(R)
            
            # Calculate absorption
            absorption = calculate_absorption(H_field, R)
            
            # Store results
            results[freq] = {
                'H_field': np.array(H_field),
                'absorption': absorption,
                'transformed_x': transformed_x,
                'transformed_y': transformed_y,
                'theta': theta,
                'R': R,
                'filename': csv_file.name
            }
            
        except Exception as e:
            print(f"Error processing {csv_file.name}: {e}")
            continue
    
    return results, sorted_frequencies


def save_absorption_data(results, sorted_frequencies, output_path):
    """Save absorption data to CSV with field and frequency columns."""
    output_path = Path(output_path)
    
    # Get field values from first measurement
    if not results:
        print("No data to save")
        return
    
    first_freq = sorted_frequencies[0]
    H_field = results[first_freq]['H_field']
    
    # Create dataframe
    data_dict = {'field': H_field}
    
    for freq in sorted_frequencies:
        data_dict[f'absorption_{freq}GHz'] = results[freq]['absorption']
    
    df = pd.DataFrame(data_dict)
    df.to_csv(output_path, index=False)
    print(f"Absorption data saved to {output_path}")
    
    return df


def plot_absorption_heatmap(results, sorted_frequencies, output_image_path, freq_range=None, H_field_range=None):
    """Plot absorption data as a heatmap/image map.

    Parameters:
    -----------
    results : dict
        Processed results dictionary with absorption data
    sorted_frequencies : list
        Sorted list of frequencies available in results
    output_image_path : str or Path
        Path to save the heatmap image
    freq_range : tuple(float, float), optional
        (min_freq, max_freq) to restrict plotted frequencies. If None, use full range.
    H_field_range : tuple(float, float), optional
        (min_H, max_H) to restrict the magnetic field range. If None, use full range.
    """
    output_image_path = Path(output_image_path)

    # Determine frequency subset
    freqs = np.array(sorted_frequencies)
    if freq_range is not None:
        fmin, fmax = freq_range
        mask = (freqs >= fmin) & (freqs <= fmax)
        if not np.any(mask):
            raise ValueError(f"No frequencies found within range {freq_range} GHz")
        freqs = freqs[mask]
    
    # Get field values from first selected frequency
    first_freq = freqs[0]
    H_field = results[first_freq]['H_field']

    # Determine field index range
    if H_field_range is not None:
        Hmin, Hmax = H_field_range
        idx_mask = (H_field >= Hmin) & (H_field <= Hmax)
        if not np.any(idx_mask):
            raise ValueError(f"No H-field values found within range {H_field_range}")
    else:
        idx_mask = slice(None)

    # Build absorption matrix for selected freq and H-field slice
    absorption_matrix = []
    for freq in freqs:
        absorption = results[freq]['absorption']
        absorption_matrix.append(absorption[idx_mask])

    absorption_matrix = np.array(absorption_matrix)

    # Determine extents for imshow
    H_vals = H_field[idx_mask]
    freq_min, freq_max = freqs.min(), freqs.max()

    fig, ax = plt.subplots(figsize=(12, 8))
    im = ax.imshow(
        absorption_matrix,
        aspect='auto',
        origin='lower',
        cmap='RdYlBu_r',
        extent=[H_vals.min(), H_vals.max(), freq_min, freq_max]
    )

    ax.set_xlabel('Magnetic Field (T)', fontsize=12)
    ax.set_ylabel('Frequency (GHz)', fontsize=12)
    ax.set_title('FMR Absorption Spectrum Map', fontsize=14)

    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('Absorption (Integrated Signal)', fontsize=12)

    plt.tight_layout()
    plt.savefig(output_image_path, dpi=300, bbox_inches='tight')
    print(f"Heatmap saved to {output_image_path}")
    plt.close()


def plot_absorption_vs_frequency(results, sorted_frequencies, field_values, output_image_path):
    """Plot absorption vs frequency for given field values.
    
    Parameters:
    -----------
    results : dict
        Dictionary containing processed absorption data
    sorted_frequencies : list
        List of sorted frequencies
    field_values : list or array
        Field values at which to extract and plot absorption
    output_image_path : str or Path
        Path to save the output image
    """
    output_image_path = Path(output_image_path)
    
    # Get field array from first result
    first_freq = sorted_frequencies[0]
    H_field = results[first_freq]['H_field']
    
    # Find indices closest to requested field values
    field_indices = []
    valid_field_values = []
    
    for field_val in field_values:
        idx = np.argmin(np.abs(H_field - field_val))
        field_indices.append(idx)
        actual_field = H_field[idx]
        valid_field_values.append(actual_field)
    
    # Create figure
    fig, ax = plt.subplots(figsize=(12, 7))
    
    # Plot absorption vs frequency for each field value
    colors = plt.cm.viridis(np.linspace(0, 1, len(field_indices)))
    
    for idx, (field_idx, actual_field) in enumerate(zip(field_indices, valid_field_values)):
        absorption_at_field = []
        
        for freq in sorted_frequencies:
            absorption = results[freq]['absorption'][field_idx]
            absorption_at_field.append(absorption)
        
        ax.plot(sorted_frequencies, absorption_at_field, 
                marker='o', linewidth=2, markersize=6,
                label=f'Field = {actual_field:.4f} T', 
                color=colors[idx])
    
    ax.set_xlabel('Frequency (GHz)', fontsize=12)
    ax.set_ylabel('Absorption (Integrated Signal)', fontsize=12)
    ax.set_title('FMR Absorption vs Frequency at Selected Field Values', fontsize=14)
    ax.legend(fontsize=10, loc='best')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_image_path, dpi=300, bbox_inches='tight')
    print(f"Absorption vs Frequency plot saved to {output_image_path}")
    plt.close()


def get_field_input_from_user(H_field):
    """Get field values input from user.
    
    Parameters:
    -----------
    H_field : array
        Available field values from data
        
    Returns:
    --------
    list : User-selected field values
    """
    print(f"\nAvailable field range: {H_field.min():.4f} T to {H_field.max():.4f} T")
    print(f"Total field points: {len(H_field)}")
    
    #user_input = input("\nEnter field values separated by commas (e.g., 0.1,0.2,0.3): ")

    user_input = "0.01,0.1,0.2"  # Default input for non-interactive environments
    user_input = "0.06"
    
    try:
        field_values = [float(x.strip()) for x in user_input.split(',')]
        
        # Validate field values
        for field_val in field_values:
            if field_val < H_field.min() or field_val > H_field.max():
                print(f"Warning: Field value {field_val} is outside available range")
        
        return field_values
    except ValueError:
        print("Invalid input. Using default field values...")
        return [H_field.min(), (H_field.min() + H_field.max()) / 2, H_field.max()]


def main(input_directory, output_directory=None, background_directory=None):
    """Main function to process all FMR data files.
    
    Parameters:
    -----------
    input_directory : str or Path
        Directory containing FMR CSV files
    output_directory : str or Path, optional
        Directory to save output files. If None, uses input directory
    """
    input_dir = Path(input_directory)
    
    if output_directory is None:
        output_dir = input_dir
    else:
        output_dir = Path(output_directory)
        output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Reading CSV files from: {input_dir}")
    results, sorted_frequencies = read_and_process_csv_files(input_dir, background_directory)
    
    if not results:
        print("No data processed")
        return
    
    print(f"\nProcessed {len(results)} files with frequencies: {sorted_frequencies} GHz")
    
    # Save absorption data
    absorption_csv = output_dir / "absorption_data.csv"
    save_absorption_data(results, sorted_frequencies, absorption_csv)
    
    # Plot heatmap (optionally restricted to a frequency and H-field range)
    heatmap_image = output_dir / "absorption_heatmap_bg_sub.png"
    # Example: only plot frequencies between 5 and 6 GHz and field between 0.005 and 0.02 T
    freq_range =(2.0, 10.0)  # e.g. (5.0, 6.0)
    H_field_range = (0, 0.15)  # e.g. (0.005, 0.02)
    plot_absorption_heatmap(results, sorted_frequencies, heatmap_image, freq_range=freq_range, H_field_range=H_field_range)
    
    # Plot absorption vs frequency at selected field values
    first_freq = sorted_frequencies[0]
    H_field = results[first_freq]['H_field']
    
    field_values = get_field_input_from_user(H_field)
    
    freq_plot_image = output_dir / "absorption_vs_frequency.png"
    plot_absorption_vs_frequency(results, sorted_frequencies, field_values, freq_plot_image)
    
    print("\nProcessing complete!")


if __name__ == "__main__":
    # Example usage
    #background_directory = r"C:\Users\Simulation\Documents\Test\FMR\background_test"
    background_directory = None  # Set to None if no background subtraction is needed
    background_directory = r"C:\Users\Simulation\Documents\Test\FMR\background_0db"
    #background_directory = r"C:\Users\Simulation\Documents\Test\FMR\background_0db_fine"
    #background_directory = r"C:\Users\Simulation\Documents\Test\FMR\background_-3db"


    # input_directory = r"C:\Users\Simulation\Documents\Test\FMR\CO_wire_long_run"
    input_directory = r"C:\Users\Simulation\Documents\Test\FMR\antidot_PY"
    #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\CO_wire_on_PY_antidot_long_run"
    # input_directory = r"C:\Users\Simulation\Documents\Test\FMR\CO_wire_90deg_long_run"
    # #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\CO_wire_on_PY_antidot_90deg_long_run"
    # #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\PY_antidot_10032026_test_freq_sweep"
    # #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\PY_antidot_45deg"
    # input_directory = r"C:\Users\Simulation\Documents\Test\FMR\background_test"
    #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\CO_wire_re_run"
    #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\antidot_PY_freq_sweep"
    #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\Leon_antidot_PY_long_scan"

    #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\Leon_antidot_PY_long_scan"
    #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\Leon_dot_Co"
    #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\Leon_dot_on_antidot_65"
    #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\Leon_py_antidot_hard"
    #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\zhehai_rect_antidot_PY_long_run"

    #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\zhehai_Co_Dots"
    #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\zhehai_wire_hard_complete"
    #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\zhehai_Co_Dots_On_PY_Antidots_complete"
    
    #input_directory = r"C:\Users\Simulation\Documents\Test\FMR\zehai_Co_Dots_rect_v2"
    output_directory = input_directory  # Save outputs in the same directory
    main(input_directory, output_directory, background_directory)
