class ConstText:
    """Текстовые константы интерфейса и отчётов."""

    MAIN_TITLE = "Программа оценки надежности сложных изделий"

    Z_title_1 = "Название организации"
    Z_title_2 = "Название изделия"

    Z_1_1 = (
        "Надёжность — это свойство объекта сохранять во времени в установленных пределах "
        "значения параметров, характеризующих способность выполнять требуемые функции."
    )

    Z_3_0 = (
        "Методика расчёта основана на применении структурных схем надежности, "
        "типовых моделей резервирования и аналитических соотношений по профильным нормативным материалам."
    )


class ConstPaths:
    REPORT_FILE = "report.html"
    MODULES_FILE_IN = "db_modules.txt"


FORMULAS = {
    "F1.1": {
        "P": r"P(t) = e^{-\sum_{i=1}^{n} \lambda_i t}",
        "T0": r"T_0 = \frac{1}{\sum_{i=1}^{n} \lambda_i}",
    },
    "F1.2": {
        "P": r"P(t) = \sum_{i=0}^{m} C_N^i e^{-(N-i)\lambda t}(1-e^{-\lambda t})^i",
        "T0": r"T_0 = \frac{1}{\lambda}\sum_{i=1}^{m+1}\frac{1}{i}",
    },
    "F1.3": {
        "P": r"P(t)=\frac{3\lambda(e^{-\lambda t}-e^{-(2\lambda+\lambda_s)t})}{3\lambda+\lambda_s}+\frac{\lambda_s e^{-\lambda t}+2\lambda e^{-(3\lambda+\lambda_s)t}}{2\lambda+\lambda_s}",
    },
    "F2.1": {
        "P": r"P(t)=e^{-t/T_0}",
        "Kg": r"K_g=\left(1+\sum_{i=1}^{n}\frac{T_{vi}}{T_{0i}}\right)^{-1}",
    },
    "F2.2": {
        "T0": r"T_0=\frac{\sum_{i=0}^{m} C_N^i (\lambda T_v)^i}{n\lambda C_N^m (\lambda T_v)^m}",
        "Kg": r"K_g=\frac{T_0}{T_0+T_v}",
    },
    "F2.4": {
        "T0": r"T_0=\frac{1}{n\lambda[\gamma+(1-\gamma)\frac{P_m}{K_g}]}",
    },
    "F3.1": {
        "P": r"P(t)\approx e^{-t/T_0}\eta_{пер}",
        "T0": r"T_0=\frac{\sum_{i=0}^{m} C_N^i \frac{1-e^{-(N-i)\lambda T_p}}{N-i}}{n\lambda C_N^m \frac{1-e^{-n\lambda T_p}}{n}}",
    },
    "F4.1": {
        "P": r"P(t)=\sum_{i=0}^{m} C_N^i e^{-(N-i)(\lambda_1+\lambda_2)t}[1-e^{-(\lambda_1+\lambda_2)t}]^i",
    },
    "F5.1": {
        "T0": r"T_0=\frac{1}{\lambda}\exp\left(\frac{t_{доп}}{T_{вн}}\right)",
        "P": r"P(t)=\exp\left(-\frac{t}{T_0}\right)",
    },
    "F6.1": {
        "P": r"P(t)=e^{-\Lambda_y t}\sum_{i=m}^{r_1} C_{r_1}^i P_1^i(t)[1-P_1(t)]^{r_1-i}",
    },
    "F6.2": {
        "P": r"P_{сист}(t)=P_y(t)\sum_{k=m}^{r_1} C_{r_1}^k P_{гр}^k(t)[1-P_{гр}(t)]^{r_1-k}",
    },
    "F6.3": {
        "P": r"P(t)=P_y(t)\sum_{k=m}^{r_1} C_{r_1}^k[P_{ур2}]^k[1-P_{ур2}]^{r_1-k}",
    },
    "F7.1": {
        "Kg": r"K_g=K_y \sum_{i=m}^{r_1} C_{r_1}^i K_1^i(1-K_1)^{r_1-i}",
    },
    "F7.2": {
        "Kg": r"K_g=K_y\sum_{i=0}^{m_{lim}} C_{r_1}^i K_1^{r_1-i}(1-K_1)^i \cdot \sum_{j=0}^{m-ir_2} C_{(r_1-i)r_2}^j K_2^{(r_1-i)r_2-j}(1-K_2)^j",
    },
}
