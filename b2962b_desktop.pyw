"""Start the B2962B console in Windows without a terminal window."""

from tkinter import messagebox


def main():
    from b2962b_output_control import run_window

    run_window()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        messagebox.showerror('B2962B 控制台 · 启动失败', str(error) or type(error).__name__)
