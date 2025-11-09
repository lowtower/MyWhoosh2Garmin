#!/usr/bin/env python3
"""
Script name: myWhoosh2Garmin.py
Usage: "python3 myWhoosh2Garmin.py"
Description:    Checks for MyNewActivity-<myWhooshVersion>.fit
                Adds avg power and heartrade
                Removes temperature
                Creates backup for the file with a timestamp as a suffix
Credits:        Garth by matin - for authenticating and uploading with
                Garmin Connect.
                https://github.com/matin/garth
                Fit_tool by mtucker - for parsing the fit file.
                https://bitbucket.org/stagescycling/python_fit_tool.git/src
                mw2gc by embeddedc - used as an example to fix the avg's.
                https://github.com/embeddedc/mw2gc
"""

import argparse
import importlib.util
import json
import logging
import os
import re
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from getpass import getpass
from pathlib import Path
from tkinter import filedialog
from typing import List

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE_PATH = SCRIPT_DIR / "myWhoosh2Garmin.log"
JSON_FILE_PATH = SCRIPT_DIR / "backup_path.json"

INSTALLED_PACKAGES_FILE = SCRIPT_DIR / "installed_packages.json"

TOKENS_PATH = SCRIPT_DIR / ".garth"
FILE_DIALOG_TITLE = "MyWhoosh2Garmin"
# Fix for https://github.com/JayQueue/MyWhoosh2Garmin/issues/2
MYWHOOSH_PREFIX_WINDOWS = "MyWhooshTechnologyService."


def setup_logging(level=logging.DEBUG) -> logging.Logger:
    """Set up logging configuration."""
    logging.basicConfig(
        level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    my_logger = logging.getLogger(__name__)
    my_logger.setLevel(level)
    file_handler = logging.FileHandler(LOG_FILE_PATH)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    my_logger.addHandler(file_handler)
    return my_logger


def load_installed_packages():
    """Load the set of installed packages from a JSON file."""
    if INSTALLED_PACKAGES_FILE.exists():
        with INSTALLED_PACKAGES_FILE.open("r") as f:
            return set(json.load(f))
    return set()


def save_installed_packages(installed_packages):
    """Save the set of installed packages to a JSON file."""
    with INSTALLED_PACKAGES_FILE.open("w") as f:
        json.dump(list(installed_packages), f)


def get_pip_command():
    """Return the pip command if pip is available."""
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return [sys.executable, "-m", "pip"]
    except subprocess.CalledProcessError:
        return None


def install_package(package):
    """Install the specified package using pip."""
    pip_command = get_pip_command()
    if pip_command:
        try:
            logger.info(f"Installing missing package: {package}.")
            subprocess.check_call(pip_command + ["install", package])
        except subprocess.CalledProcessError as e:
            logger.exception(f"Error installing < {package} >: {e}.")
    else:
        logger.debug("pip is not available. Unable to install packages.")


def ensure_packages():
    """Ensure all required packages are installed and tracked."""
    required_packages = ["garth", "fit_tool"]
    installed_packages = load_installed_packages()

    for package in required_packages:
        if package in installed_packages:
            logger.info(f"Package < {package} > is already tracked as installed.")
            continue

        if not importlib.util.find_spec(package):
            logger.info(f"Package < {package} > not found.Attempting to install...")
            install_package(package)

        try:
            __import__(package)
            logger.info(f"Successfully imported < {package} >.")
            installed_packages.add(package)
        except ModuleNotFoundError:
            logger.exception(f"Failed to import < {package} > even after installation.")

    save_installed_packages(installed_packages)


# Imports
try:
    import garth
    from fit_tool.fit_file import FitFile
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.file_creator_message import FileCreatorMessage
    from fit_tool.profile.messages.file_id_message import FileIdMessage
    from fit_tool.profile.messages.lap_message import LapMessage
    from fit_tool.profile.messages.record_message import (
        RecordMessage,
        RecordTemperatureField,
    )
    from fit_tool.profile.messages.session_message import SessionMessage
    from garth.exc import GarthException, GarthHTTPError
except ImportError as e:
    logger = logging.getLogger(__name__)
    logger.exception(f"Error importing modules: {e}")


def get_fitfile_location() -> Path:
    """
    Get the location of the FIT file directory based on the operating system.

    Returns:
        Path: The path to the FIT file directory.

    Raises:
        RuntimeError: If the operating system is unsupported.
        SystemExit: If the target path does not exist.
    """
    if os.name == "posix":  # macOS and Linux
        target_path = (
            Path.home()
            / "Library"
            / "Containers"
            / "com.whoosh.whooshgame"
            / "Data"
            / "Library"
            / "Application Support"
            / "Epic"
            / "MyWhoosh"
            / "Content"
            / "Data"
        )
        if target_path.is_dir():
            return target_path
        else:
            logger.exception(
                f"Target path < {target_path} > does not exist. Check your MyWhoosh installation."
            )
            sys.exit(1)
    elif os.name == "nt":  # Windows
        try:
            base_path = Path.home() / "AppData" / "Local" / "Packages"
            for directory in base_path.iterdir():
                if directory.is_dir() and directory.name.startswith(
                    MYWHOOSH_PREFIX_WINDOWS
                ):
                    target_path = (
                        directory
                        / "LocalCache"
                        / "Local"
                        / "MyWhoosh"
                        / "Content"
                        / "Data"
                    )
            if target_path.is_dir():
                return target_path
            else:
                raise FileNotFoundError(
                    f"No valid MyWhoosh directory found in < {target_path} >."
                )
        except FileNotFoundError as e:
            logger.exception(str(e))
        except PermissionError as e:
            logger.exception(f"Permission denied: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
    else:
        logger.exception("Unsupported OS")
        return Path()


def get_backup_path(args: dict) -> Path | None:
    """
    This function checks if a backup path already exists in a JSON file.
    If it does, it returns the stored path. If the file does not exist,
    it prompts the user to select a directory via a file dialog, saves
    the selected path to the JSON file, and returns it.

    Args:
        args (dict): command line arguments, optionally containing username and password

    Returns:
        str or None: The selected backup path or None if no path was selected.
    """
    json_file = JSON_FILE_PATH
    if "backup_location" in args.keys() and args["backup_location"]:
        backup_path = Path.cwd() / args["backup_location"]
        if backup_path.is_dir():
            logger.info(f"Using backup path from command line: < {backup_path} >.")
            with json_file.open("w") as f:
                json.dump({"backup_path": backup_path.name}, f)
            logger.info(f"Backup path saved to < {json_file} >.")
            return Path(backup_path)
    else:
        if json_file.is_file():
            with json_file.open("r") as f:
                backup_path = Path(json.load(f).get("backup_path"))
            if backup_path and backup_path.is_dir():
                logger.info(f"Using backup path from JSON: < {backup_path} >.")
                return Path(backup_path)
            else:
                logger.exception("Invalid backup path stored in JSON.")
                sys.exit(1)
        else:
            root = tk.Tk()
            root.withdraw()
            backup_path = filedialog.askdirectory(
                title=f"Select {FILE_DIALOG_TITLE} Backup Directory"
            )
            if not backup_path:
                logger.info("No directory selected, exiting.")
                return Path()
            with json_file.open("w") as f:
                json.dump({"backup_path": backup_path}, f)
            logger.info(f"Backup path saved to < {json_file} >.")
    return Path(backup_path)


def get_credentials_for_garmin(args: dict):
    """
    Take command line arguments or prompt the user for Garmin credentials and authenticate using Garth.

    Args:
        args (dict): command line arguments, optionally containing username and password

    Returns:
        None

    Exits:
        Exits with status 1 if authentication fails.
    """
    if (
        "garmin_username" in args.keys()
        and args["garmin_username"]
        and "garmin_password" in args.keys()
        and args["garmin_password"]
    ):
        username = args["garmin_username"]
        password = args["garmin_password"]
    else:
        username = input("Username: ")
        password = getpass("Password: ")
    logger.info("Authenticating...")
    try:
        garth.login(username, password)
        garth.save(TOKENS_PATH)
        logger.info("")
        logger.info("Successfully authenticated!")
    except GarthHTTPError:
        logger.info("Wrong credentials. Please check username and password.")
        sys.exit(1)


def authenticate_to_garmin(args: dict):
    """
    Authenticate the user to Garmin by checking for existing tokens and
    resuming the session, or prompting for credentials if no session
    exists or the session is expired.

    Args:
        args (dict): command line arguments, optionally containing username and password

    Returns:
        None

    Exits:
        Exits with status 1 if authentication fails.
    """
    try:
        if TOKENS_PATH.exists():
            garth.resume(TOKENS_PATH)
            try:
                logger.info(f"Authenticated as: {garth.client.username}")
            except GarthException:
                logger.info("Session expired. Re-authenticating...")
                get_credentials_for_garmin(args)
        else:
            logger.info("No existing session. Please log in.")
            get_credentials_for_garmin(args)
    except GarthException as e:
        logger.info(f"Authentication error: {e}")
        sys.exit(1)


def calculate_avg(values: iter) -> int:
    """
    Calculate the average of a list of values, returning 0 if the list is empty.

    Args:
        values (List[float]): The list of values to average.

    Returns:
        float: The average value or 0 if the list is empty.
    """
    return sum(values) / len(values) if values else 0


def append_value(values: List[int], message: object, field_name: str) -> None:
    """
    Appends a value to the 'values' list based on a field from 'message'.

    Args:
        values (List[int]): The list to append the value to.
        message (object): The object that holds the field value.
        field_name (str): The name of the field to retrieve from the message.

    Returns:
        None
    """
    value = getattr(message, field_name, None)
    values.append(value if value else 0)


def reset_values() -> tuple[List[int], List[int], List[int], List[int]]:
    """
    Resets and returns three empty lists for cadence, power
    and heart rate values.

    Returns:
        tuple: A tuple containing three empty lists
        (laps, cadence, power, and heart rate).
    """
    return [], [], [], []


def cleanup_fit_file(fit_file_path: Path, new_file_path: Path) -> None:
    """
    Clean up the FIT file by processing and removing unnecessary fields.
    Also, calculate average values for cadence, power, and heart rate.

    Args:
        fit_file_path (Path): The path to the input FIT file.
        new_file_path (Path): The path to save the processed FIT file.

    Returns:
        None
    """
    builder = FitFileBuilder()
    fit_file = FitFile.from_file(str(fit_file_path))
    lap_values, cadence_values, power_values, heart_rate_values = reset_values()

    for record in fit_file.records:
        message = record.message
        if isinstance(message, LapMessage):
            append_value(lap_values, message, "start_time")
            append_value(lap_values, message, "total_elapsed_time")
            append_value(lap_values, message, "total_distance")
            append_value(lap_values, message, "avg_speed")
            append_value(lap_values, message, "max_speed")
            append_value(lap_values, message, "avg_heart_rate")
            append_value(lap_values, message, "max_heart_rate")
            append_value(lap_values, message, "avg_cadence")
            append_value(lap_values, message, "max_cadence")
            append_value(lap_values, message, "total_calories")
        if isinstance(message, RecordMessage):
            message.remove_field(RecordTemperatureField.ID)
            append_value(cadence_values, message, "cadence")
            append_value(power_values, message, "power")
            append_value(heart_rate_values, message, "heart_rate")
        if isinstance(message, SessionMessage):
            if not message.avg_cadence:
                message.avg_cadence = calculate_avg(cadence_values)
            if not message.avg_power:
                message.avg_power = calculate_avg(power_values)
            if not message.avg_heart_rate:
                message.avg_heart_rate = calculate_avg(heart_rate_values)
            if not message.avg_speed or message.avg_speed == 0:
                message.avg_speed = message.total_distance / message.total_timer_time
            lap_values, cadence_values, power_values, heart_rate_values = reset_values()
        if isinstance(message, FileIdMessage):
            # Override manufacturer/product but keep other fields
            message.manufacturer = 1
            message.product = 1836
        builder.add(message)
    builder.build().to_file(str(new_file_path))
    logger.info(f"Cleaned-up file saved as < {SCRIPT_DIR}/{new_file_path.name} >.")


def get_fit_files(fitfile_location: Path) -> list:
    """Returns a list of all .fit files based in the fitfile location.

    Args:
        fitfile_location (Path): location with .fit files to be processed

    Returns:
        list: list of all .fit files based in the fitfile location
    """
    return [fit_file for fit_file in fitfile_location.glob("*.fit")]


def get_most_recent_fit_file(fitfile_location: Path) -> Path:
    """
    Returns the most recent .fit file based
    on versioning in the filename.
    """
    fit_files = fitfile_location.glob("*.fit")
    fit_files = sorted(
        fit_files,
        key=lambda f: tuple(map(int, re.findall(r"(\d+)", f.stem.split("-")[-1]))),
        reverse=True,
    )
    return fit_files[0] if fit_files else Path()


def generate_new_filename(fit_file: Path) -> str:
    """Generates a new filename with a timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return f"{fit_file.stem}_{timestamp}.fit"


def cleanup_and_save_fit_file(fitfile_location: Path) -> Path:
    """
    Clean up the most recent .fit file in a directory and save it
    with a timestamped filename.

    Args:
        fitfile_location (Path): The directory containing the .fit files.

    Returns:
        Path: The path to the newly saved and cleaned .fit file,
        or an empty Path if no .fit file is found or if the path is invalid.
    """
    fit_file = fitfile_location
    if fitfile_location.is_dir():
        logger.debug(f"Checking for .fit files in directory: < {fitfile_location} >.")
        fit_file = get_most_recent_fit_file(fitfile_location)

    if not fit_file:
        logger.info("No .fit files found.")
        return Path()

    logger.debug(f"Found the most recent .fit file: < {fit_file.name} >.")
    new_filename = generate_new_filename(fit_file)

    if not BACKUP_FITFILE_LOCATION.exists():
        logger.exception(
            f"The backup directory < {BACKUP_FITFILE_LOCATION} > does not exist. Did you delete it?"
        )
        return Path()

    new_file_path = BACKUP_FITFILE_LOCATION / new_filename
    logger.info(f"Cleaning up {new_file_path}.")

    try:
        cleanup_fit_file(fit_file, new_file_path)
        logger.info(
            f"Successfully cleaned < {fit_file.name} > and saved it as < {new_file_path.name} >."
        )
        return new_file_path
    except Exception as e:
        logger.exception(f"Failed to process < {fit_file.name} >: {e}.")
        return Path()


def upload_fit_file_to_garmin(new_file_path: Path):
    """
    Upload a .fit file to Garmin using the Garth client.

    Args:
        new_file_path (Path): The path to the .fit file to upload.

    Returns:
        None
    """
    try:
        if new_file_path and new_file_path.exists():
            with open(new_file_path, "rb") as f:
                uploaded = garth.client.upload(f)
                logger.debug(uploaded)
        else:
            logger.info(f"Invalid file path: {new_file_path}.")
    except GarthHTTPError:
        logger.info("Duplicate activity found on Garmin Connect.")


def parse_arguments() -> dict:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Upload my whoosh fit file(s) from given directory to Garmin"
    )
    parser.add_argument(
        "--fit-file-location",
        metavar="PATH",
        required=True,
        help="the path to the fit file directory",
    )
    parser.add_argument(
        "--backup-location",
        metavar="PATH",
        required=False,
        help="the path to the backup directory",
    )
    parser.add_argument(
        "--garmin-username",
        metavar="USERNAME",
        required=False,
        help="the garmin username for upload",
    )
    parser.add_argument(
        "--garmin-password",
        metavar="PASSWORD",
        required=False,
        help="the garmin password for upload",
    )
    parser.add_argument(
        "--loglevel",
        default="DEBUG",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level",
    )
    return vars(parser.parse_args())


def main(args: dict):
    """
    Main function to authenticate to Garmin, clean and save the FIT file,
    and upload it to Garmin.

    Returns:
        None
    """
    logger.info("Starting MyWhoosh2Garmin...")
    logger.info(f"FIT file location: < {args['fit_file_location']} >.")
    authenticate_to_garmin(args)
    new_file_path = cleanup_and_save_fit_file(Path(args["fit_file_location"]))
    if new_file_path:
        upload_fit_file_to_garmin(new_file_path)


if __name__ == "__main__":
    # get command line arguments
    cli_args = parse_arguments()
    # Convert the log level from string to the appropriate logging level
    numeric_level = getattr(logging, cli_args["loglevel"].upper())
    # setup logging
    logger = setup_logging(level=numeric_level)
    # ensure packages
    ensure_packages()

    logger.info("")
    BACKUP_FITFILE_LOCATION = get_backup_path(cli_args)
    main(cli_args)
    logger.info("")
