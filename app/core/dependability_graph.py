import math
import random
import collections
from typing import Dict, List, Set, Optional, Tuple

class Graph:
    """
    Класс для работы с графом надежности (RBD - Reliability Block Diagram).
    Поддерживает поиск путей и расчет вероятности безотказной работы (ВБР).
    """

    def __init__(self):
        # Список смежности: { "Имя_Узла": ["Сосед1", "Сосед2"] }
        self.adj: Dict[str, List[str]] = collections.defaultdict(list)
        # Свойства блоков: { "Имя_Узла": {"lambda": 0.001, "Tv": 10.0} }
        self.blocks_data: Dict[str, Dict[str, float]] = {}
        # Кэш для найденных путей
        self.all_paths: List[List[str]] = []

    def add_node(self, name: str, props: Optional[Dict[str, object]] = None):
        """Добавление вершины (блока) с параметрами надежности"""
        if name not in self.adj:
            self.adj[name] = []
        clean_props = {}
        if props:
            # Нормализация ключей (защита от разного регистра)
            for k, v in props.items():
                key_lower = str(k).lower()
                if key_lower.startswith("lam"):
                    clean_props["lambda"] = float(v)
                elif key_lower in {"tv", "tв"}:
                    clean_props["Tv"] = float(v)
                elif key_lower == "t":
                    clean_props["t"] = float(v)
                else:
                    try:
                        clean_props[k] = float(v)
                    except (TypeError, ValueError):
                        clean_props[k] = v
        self.blocks_data[name] = clean_props

    def add_edge(self, u: str, v: str):
        """Добавление направленной связи (от U к V)"""
        # RBD - это ориентированный граф (ток идет от входа к выходу)
        if v not in self.adj[u]:
            self.adj[u].append(v)

    def find_all_paths(self, start_node: str, end_node: str) -> List[List[str]]:
        """
        Поиск всех простых путей от start_node к end_node (DFS).
        """
        self.all_paths = []
        visited: Set[str] = set()
        path: List[str] = []
        
        # Проверка на существование узлов
        if start_node not in self.adj and start_node not in self.blocks_data:
            return []
            
        self._dfs(start_node, end_node, visited, path)
        return self.all_paths

    def _dfs(self, u: str, d: str, visited: Set[str], path: List[str]):
        """Рекурсивный обход в глубину"""
        visited.add(u)
        path.append(u)

        if u == d:
            self.all_paths.append(list(path))
        else:
            for v in self.adj[u]:
                if v not in visited:
                    self._dfs(v, d, visited, path)

        path.pop()
        visited.remove(u)

    def calculate_probability_approx(self, t: float) -> float:
        """
        Метод 1: Приближенный расчет (Нижняя граница надежности).
        Считает пути как параллельное соединение.
        ВНИМАНИЕ: Если элементы повторяются в разных путях (сложная структура),
        этот метод дает погрешность. Для точного расчета используйте Monte Carlo.
        """
        if not self.all_paths:
            return 0.0
        
        # Q_sys = Произведение (Вероятность отказа каждого пути)
        # P_sys = 1 - Q_sys
        q_sys = 1.0
        
        for path in self.all_paths:
            # P_path = Произведение P_элементов (последовательное соединение)
            p_path = 1.0
            for node in path:
                # Старт и Конец обычно идеальны (P=1), если у них нет свойств
                if node in self.blocks_data:
                    lam = self.blocks_data[node].get("lambda", 0.0)
                    # Формула P(t) = exp(-lambda * t)
                    p_node = math.exp(-lam * t)
                    p_path *= p_node
            
            # Вероятность отказа этого пути
            q_path = 1.0 - p_path
            q_sys *= q_path
            
        return 1.0 - q_sys

    def calculate_reliability_monte_carlo(self, t: float, simulations: int = 10000, start_node: str = "Start", end_node: str = "End") -> float:
        """
        Метод 2: Имитационное моделирование (Монте-Карло).
        Дает ТОЧНЫЙ результат для любой сложности схемы (мостики, сложные связи).
        
        Алгоритм:
        1. Для каждой симуляции "бросаем кубик" для каждого блока (сломался или нет).
        2. Проверяем, есть ли путь от Старта к Концу через "живые" блоки.
        3. P(t) = Число успехов / Число симуляций.
        """
        if simulations <= 0:
            raise ValueError("simulations must be a positive integer.")

        if start_node not in self.adj and start_node not in self.blocks_data:
             # Если граф пустой или нет старта
             return 0.0

        success_count = 0
        
        # Предварительно рассчитываем вероятности каждого блока, чтобы не считать в цикле
        block_probs = {}
        for name, props in self.blocks_data.items():
            lam = props.get("lambda", 0.0)
            block_probs[name] = math.exp(-lam * t)

        for _ in range(simulations):
            # 1. Определение состояния системы (кто жив, кто мертв)
            # set 'active_nodes' содержит имена работающих блоков
            active_nodes = set()
            active_nodes.add(start_node)
            active_nodes.add(end_node)
            
            for name, prob in block_probs.items():
                if random.random() <= prob:
                    active_nodes.add(name)

            # 2. Проверка связности (BFS - поиск в ширину)
            # Есть ли путь от Start к End только по active_nodes?
            if self._is_connected_bfs(start_node, end_node, active_nodes):
                success_count += 1

        return success_count / simulations

    def _is_connected_bfs(self, start: str, end: str, active_nodes: Set[str]) -> bool:
        """Быстрый поиск пути только по живым узлам"""
        if start not in active_nodes or end not in active_nodes:
            return False
            
        queue = collections.deque([start])
        visited = {start}
        
        while queue:
            u = queue.popleft()
            if u == end:
                return True
            
            for v in self.adj[u]:
                if v in active_nodes and v not in visited:
                    visited.add(v)
                    queue.append(v)
        
        return False
