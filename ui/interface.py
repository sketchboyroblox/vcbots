import time
import os
from colorama import init, Fore, Style

init(autoreset=True)

def display_ansi_art():
    art_lines = [
        " ██▒   █▓▄████▄      ▄▄▄▄   ▒█████ ▄▄▄█████▓ ██████ ",
        "▓██░   █▒██▀ ▀█     ▓█████▄▒██▒  ██▓  ██▒ ▓▒██    ▒ ",
        " ▓██  █▒▒▓█    ▄    ▒██▒ ▄█▒██░  ██▒ ▓██░ ▒░ ▓██▄   ",
        "  ▒██ █░▒▓▓▄ ▄██▒   ▒██░█▀ ▒██   ██░ ▓██▓ ░  ▒   ██▒",
        "   ▒▀█░ ▒ ▓███▀ ░   ░▓█  ▀█░ ████▓▒░ ▒██▒ ░▒██████▒▒",
        "   ░ ▐░ ░ ░▒ ▒  ░   ░▒▓███▀░ ▒░▒░▒░  ▒ ░░  ▒ ▒▓▒ ▒ ░",
        "   ░ ░░   ░  ▒      ▒░▒   ░  ░ ▒ ▒░    ░   ░ ░▒  ░ ░",
        "     ░░ ░            ░    ░░ ░ ░ ▒   ░     ░  ░  ░  ",
        "      ░ ░ ░          ░         ░ ░               ░  ",
        "     ░  ░                 ░                         "
    ]
    
    colors = [
        Fore.BLUE,
        Fore.BLUE + Style.BRIGHT,
        "\033[38;5;21m",
        "\033[38;5;27m", 
        "\033[38;5;33m",
        "\033[38;5;39m",
        "\033[38;5;45m",
        "\033[38;5;51m",
        Fore.CYAN,
        Fore.CYAN + Style.BRIGHT
    ]
    
    os.system('cls' if os.name == 'nt' else 'clear')
    
    terminal_width = os.get_terminal_size().columns
    
    for i, line in enumerate(art_lines):
        color = colors[i]
        centered_line = line.center(terminal_width)
        print(f"{color}{centered_line}")
        time.sleep(0.1)
    
    print(Style.RESET_ALL)

if __name__ == "__main__":
    display_ansi_art()
