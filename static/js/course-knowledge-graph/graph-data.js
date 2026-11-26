// 节点逐行对应两份教学大纲第四节的「理论教学内容与要求」。
// sourcePage 为 PDF 实际页码。跨页行记起始页。关系为教学推导，待课程教师审阅。

const courses = [
  {
    id: "programming",
    name: "程序设计基础A",
    shortName: "程序设计基础A",
    color: "#3c7ef1",
    outlineCode: "1010001114",
    outlineRevision: 2025,
    chapters: [
      { id: "p-overview", name: "C 语言概述及算法基础" },
      { id: "p-sequence", name: "顺序结构程序设计" },
      { id: "p-branch", name: "选择结构程序设计" },
      { id: "p-loop", name: "循环结构程序设计" },
      { id: "p-array", name: "数组" },
      { id: "p-function", name: "函数" },
      { id: "p-struct", name: "结构体" },
      { id: "p-pointer", name: "指针" },
      { id: "p-list", name: "链表" },
      { id: "p-file", name: "文件" },
    ],
  },
  {
    id: "algorithms",
    name: "数据结构与算法",
    shortName: "数据结构与算法",
    color: "#8d62df",
    outlineCode: "1010002107",
    outlineRevision: 2024,
    chapters: [
      { id: "a-intro", name: "绪论" },
      { id: "a-linear", name: "线性表" },
      { id: "a-stack", name: "栈和队列" },
      { id: "a-tree", name: "树和二叉树" },
      { id: "a-huffman", name: "哈夫曼树" },
      { id: "a-graph", name: "图的结构与遍历" },
      { id: "a-graph-app", name: "图的应用" },
      { id: "a-search", name: "查找" },
      { id: "a-sort", name: "排序" },
    ],
  },
];

const points = [];
function addChapterPoints(course, chapter, entries) {
  for (const [id, shortName, name, sourcePage, description] of entries) {
    points.push({ id, course, chapter, shortName, name, sourcePage, description });
  }
}

addChapterPoints("programming", "p-overview", [
  ["program_execution", "C 程序执行过程", "C 程序执行过程", 3, "了解最简单的 C 程序，掌握运行 C 程序的步骤与方法。"],
  ["algorithm_design", "算法描述与设计", "算法描述、算法设计", 3, "认识算法特点，使用描述语言和流程图表达解决工程问题的步骤。"],
]);
addChapterPoints("programming", "p-sequence", [
  ["basic_syntax", "数据类型与基本语法", "数据类型、表达式、C 语言基本语法", 3, "认识变量、类型转换、运算符和表达式，为客观事物选择合适的数据类型。"],
  ["sequence_io", "顺序结构与输入输出", "输入输出格式控制、数值计算、顺序综合应用", 3, "运用格式化输入输出和数值计算实现顺序结构程序。"],
]);
addChapterPoints("programming", "p-branch", [
  ["conditions", "关系与逻辑表达式", "关系表达式、逻辑表达式", 4, "掌握关系与逻辑运算符及组合表达式。"],
  ["branch_statements", "if 与 switch", "if 语句、switch 语句", 4, "用条件分支和情况分支表达多种处理路径。"],
  ["nested_branch", "嵌套分支", "分支嵌套、选择结构综合应用", 4, "把多情况复杂问题转换为嵌套分支算法。"],
]);
addChapterPoints("programming", "p-loop", [
  ["loop_design", "循环设计思想", "循环结构设计思想", 4, "理解重复执行的设计思想，认识循环与顺序、选择的联系。"],
  ["single_loop", "单循环", "单循环程序设计", 4, "掌握 for、while、do while 语句及循环控制。"],
  ["nested_loop", "多重循环", "多循环程序设计", 4, "处理嵌套重复过程，掌握多重循环控制与提前终止。"],
]);
addChapterPoints("programming", "p-array", [
  ["array", "数组定义与引用", "数组的定义、数组引用", 4, "理解数组存储与内存分配，掌握定义和下标访问。"],
  ["array_initialization", "一维数组应用", "数组的初始化、数组的引用、一维数组应用", 4, "将同类元素组织为一维数组，练习初始化、遍历与应用。"],
  ["string", "字符串与二维数组", "字符串定义、字符串应用、二维数组应用", 4, "掌握字符数组、字符串函数和二维数组在工程问题中的应用。"],
  ["array_application", "数组综合应用", "数组应用程序设计", 4, "结合数组与三种基本控制结构解决工程问题。"],
]);
addChapterPoints("programming", "p-function", [
  ["function", "函数定义与调用", "函数定义、函数调用", 4, "理解函数的设计思想，掌握定义和调用方法。"],
  ["function_application", "函数应用", "函数应用", 4, "用模块化程序设计方法分解复杂工程问题。"],
  ["recursion", "递归与变量作用域", "递归函数应用、变量的生存周期和作用范围", 5, "理解递归调用与终止过程，区分全局变量、局部变量及其作用范围。"],
]);
addChapterPoints("programming", "p-struct", [
  ["struct", "结构体定义与成员", "结构体类型定义、结构体变量定义和结构体变量成员引用方法", 5, "区分结构体类型与变量，定义并引用成员。"],
  ["struct_array", "结构体数组", "结构体数组定义及使用", 5, "理解结构体数组的存储形式，构造封装不同数据类型的数据结构。"],
  ["struct_application", "结构体综合应用", "结构体数组应用、结构体与函数应用", 5, "用结构体数组、函数和控制结构对工程数据进行模块化处理。"],
]);
addChapterPoints("programming", "p-pointer", [
  ["pointer", "指针变量", "指针变量定义、指针变量应用", 5, "理解指针和寻址，比较数组访问、结构体成员和指针访问形式。"],
  ["pointer_parameters", "指针作函数参数", "指针做参数的函数调用", 5, "理解指针传参的原理，用函数表达传递大量数据的处理过程。"],
]);
addChapterPoints("programming", "p-list", [
  ["dynamic_memory", "动态内存与链表节点", "动态内存分配、链表的定义", 5, "掌握动态内存分配和释放，定义链表节点。"],
  ["list_creation", "链表创建", "链表的创建", 5, "掌握动态创建单向链表的头插法与尾插法。"],
  ["list_traversal", "链表遍历与查找", "链表的遍历、链表查找", 5, "顺序访问链表并定位满足条件的节点。"],
  ["list_update", "链表插入与删除", "链表的插入、链表的删除", 5, "修改单向链表链接，分析用数组、结构体数组或链表表示问题的取舍。"],
  ["list_application", "链表综合应用", "链表综合应用", 5, "把单链表结构用于完整的实际问题。"],
]);
addChapterPoints("programming", "p-file", [
  ["file_io", "文件基础与开关", "文件基本知识，文件的打开/关闭", 6, "了解文件分类、缓冲区和文件结构，掌握打开和关闭文件。"],
  ["file_operations", "文件读写与定位", "文件的读/写操作，文件指针移动方法，文件相关函数", 6, "使用文件读写、定位和出错检查方法存取文本数据。"],
]);

addChapterPoints("algorithms", "a-intro", [
  ["abstract_data_type", "数据结构与 ADT", "数据结构的基本概念，抽象数据类型的表示与实现", 3, "认识数据结构、抽象数据类型及其表示与实现。"],
  ["algorithm_analysis", "算法描述与分析", "算法描述和算法分析", 3, "列举算法特点，分析给定算法的时间和空间复杂度。"],
]);
addChapterPoints("algorithms", "a-linear", [
  ["linear_list_adt", "线性表 ADT", "线性表的抽象数据类型定义", 4, "从元素顺序和基本操作理解线性表的抽象定义。"],
  ["linear_list_operations", "线性表复杂操作", "复杂操作表示", 4, "用线性表的基本操作组合表示复杂操作。"],
  ["sequential_list", "顺序表的实现", "线性表的顺序表示和实现", 4, "定义顺序表的存储类型，分析和实现基本元素操作。"],
  ["linked_list", "链表的实现", "线性表的链式表示和实现", 4, "定义线性表的链式存储，分析和实现链表的基本算法。"],
  ["list_variants", "循环链表与双向链表", "循环链表与双向链表", 4, "理解循环和双向链表的类型定义及关键算法。"],
  ["linear_list_application", "线性表的应用", "线性表的应用", 4, "选择适用的线性表表示，设计并实现具体问题的算法。"],
]);
addChapterPoints("algorithms", "a-stack", [
  ["stack_queue_adt", "栈与队列 ADT", "栈的抽象数据类型定义，队列的抽象数据类型定义", 4, "理解栈和队列的抽象定义及后进先出、先进先出的工作原理。"],
  ["stack", "栈的实现", "栈的表示及实现", 4, "分析栈操作的核心逻辑，实现入栈和出栈等基本算法。"],
  ["queue", "队列的实现", "队列的表示及实现", 4, "分析队列操作的核心逻辑，实现入队和出队等基本算法。"],
  ["stack_recursion", "栈与递归", "栈与递归", 4, "用栈解释递归调用的状态保存，并用两者解决相应问题。"],
  ["stack_queue_application", "栈与队列的应用", "栈与队列的应用", 4, "根据操作顺序选用栈或队列，实现具体应用中的算法。"],
]);
addChapterPoints("algorithms", "a-tree", [
  ["tree", "树与二叉树定义", "树的抽象数据类型定义，二叉树的定义与性质", 4, "理解树的抽象数据类型以及二叉树的定义与性质。"],
  ["binary_tree_storage", "二叉树存储", "二叉树的存储结构", 4, "定义顺序存储、二叉链表，并了解三叉链表表示。"],
  ["tree_recursive", "二叉树递归遍历", "二叉树的创建与递归遍历算法", 4, "掌握二叉树的创建与递归遍历思想，能分析并实现算法。"],
  ["tree_iterative", "二叉树非递归遍历", "二叉树的非递归遍历算法", 4, "理解并实现二叉树的非递归遍历算法。"],
  ["tree_application", "二叉树的应用", "二叉树的应用", 4, "运用遍历算法解决与二叉树相关的实际问题。"],
  ["forest", "树、森林与二叉树", "树的存储结构；树及森林的遍历；树、森林与二叉树的相互转换", 5, "掌握一般树的存储以及树与森林遍历，理解与二叉树的相互转换。"],
]);
addChapterPoints("algorithms", "a-huffman", [
  ["huffman_principles", "哈夫曼树与编码原理", "哈夫曼树存储结构与编码原理", 5, "定义哈夫曼树的存储结构，理解构建和编码原理。"],
  ["huffman_algorithms", "哈夫曼树构建与编码", "哈夫曼树创建与编码算法", 5, "分析并实现哈夫曼树构建、编码和实际应用。"],
]);
addChapterPoints("algorithms", "a-graph", [
  ["graph", "图的定义与存储", "图的定义、基本概念；图的存储结构", 5, "理解图的基本概念，掌握邻接矩阵和邻接表表示。"],
  ["graph_traversal", "图的遍历", "图的遍历", 5, "掌握图遍历思想，分析实现基本遍历算法及相关应用。"],
]);
addChapterPoints("algorithms", "a-graph-app", [
  ["minimum_spanning_tree", "连通性与最小生成树", "图的连通性及最小生成树", 5, "理解连通性，分析并实现普里姆与克鲁斯卡尔算法。"],
  ["topological_sort", "拓扑排序", "拓扑排序", 5, "理解拓扑排序的思想，分析实现基本算法及应用。"],
  ["critical_path", "关键路径", "关键路径", 5, "理解关键路径的概念和求解思想，实现基本算法及应用。"],
  ["shortest_path", "最短路径", "最短路径", 5, "掌握最短路径的求解思想，分析实现基本算法及应用。"],
]);
addChapterPoints("algorithms", "a-search", [
  ["searching", "静态查找", "静态查找", 5, "分析并实现顺序查找和折半查找，比较算法效率。"],
  ["dynamic_search", "动态查找", "动态查找", 5, "理解二叉排序树、二叉平衡树及创建方法，实现二叉排序树的基本算法。"],
  ["hash_table", "哈希表", "哈希表", 6, "结合冲突处理构造哈希表，分析查找效率。"],
]);
addChapterPoints("algorithms", "a-sort", [
  ["sorting_basics", "排序的基本概念", "排序的基本概念", 6, "理解排序的目标、基本概念与原理。"],
  ["sorting_ideas", "排序的基本思想", "排序的基本思想", 6, "掌握插入、交换、选择与归并排序的算法思想。"],
  ["sorting", "排序算法", "排序算法", 6, "分析并实现插入排序、交换排序、选择排序和归并排序。"],
  ["sorting_comparison", "排序算法的比较", "排序算法的比较", 6, "比较插入、交换、选择、归并和基数排序的特点。"],
]);

const edges = [];
function addRelationships(type, entries) {
  for (const [source, target, reason] of entries) {
    edges.push({ source, target, type, reason });
  }
}

addRelationships("prerequisite", [
  ["basic_syntax", "sequence_io", "顺序计算和格式化读写需要识别变量类型并使用表达式。"],
  ["basic_syntax", "conditions", "关系与逻辑表达式由变量、操作数和运算符组成。"],
  ["conditions", "branch_statements", "if 的分支条件依赖可求值的关系或逻辑表达式。"],
  ["branch_statements", "nested_branch", "嵌套分支通过在已有分支内加入新的选择语句实现。"],
  ["loop_design", "single_loop", "编写单循环前需要确定循环条件、重复任务与终止方式。"],
  ["conditions", "single_loop", "循环控制条件通常由关系或逻辑表达式表示。"],
  ["single_loop", "nested_loop", "多重循环将多个单循环分层组合。"],
  ["basic_syntax", "array", "定义数组时需要指定元素类型，并用整型下标访问元素。"],
  ["array", "array_initialization", "初始化一维数组前需要先理解它的定义和下标。"],
  ["array", "string", "C 字符串与二维数组的定义都依赖数组的基本表示。"],
  ["array_initialization", "array_application", "用数组解题时需要会初始化、访问和遍历一维数组。"],
  ["single_loop", "array_application", "数组综合问题常通过循环依次处理元素。"],
  ["basic_syntax", "function", "函数声明和调用涉及参数及返回值的数据类型。"],
  ["function", "function_application", "模块化设计需要会定义、调用和组合函数。"],
  ["function", "recursion", "理解函数调用与返回是跟踪递归执行的基础。"],
  ["struct", "struct_array", "定义结构体数组前需要先定义结构体类型和成员。"],
  ["array", "struct_array", "结构体数组仍使用数组定义与下标访问。"],
  ["struct_array", "struct_application", "结构体综合问题需要先能创建和操作结构体记录数组。"],
  ["function", "struct_application", "结构体与函数配合时需要掌握函数定义和调用。"],
  ["basic_syntax", "pointer", "定义指针需要区分变量、类型和赋值。"],
  ["pointer", "pointer_parameters", "指针传参需要理解保存地址、解引用和间接访问。"],
  ["function", "pointer_parameters", "用指针传参前需要理解参数与函数调用方式。"],
  ["pointer", "dynamic_memory", "动态分配返回地址，链表节点也用指针记录链接。"],
  ["struct", "dynamic_memory", "链表节点以结构体组合数据字段和指针字段。"],
  ["dynamic_memory", "list_creation", "动态建立链表时，需要先定义节点并申请空间。"],
  ["list_creation", "list_traversal", "遍历从已建链表的头节点沿链接访问后续节点。"],
  ["list_traversal", "list_update", "插入和删除通常要先查找到相关节点或其前驱。"],
  ["list_update", "list_application", "动态管理实际记录需要会插入和删除现有节点。"],
  ["file_io", "file_operations", "读取、写入或定位文件前需要成功打开文件流。"],
  ["abstract_data_type", "linear_list_adt", "线性表是抽象数据类型的具体实例。"],
  ["linear_list_adt", "linear_list_operations", "组合复杂操作前要理解线性表的基本操作。"],
  ["linear_list_adt", "sequential_list", "顺序表的存储和操作对应线性表的抽象定义。"],
  ["linear_list_adt", "linked_list", "链式表示实现线性表抽象定义的操作。"],
  ["linked_list", "list_variants", "循环和双向链表在链式表示上改变节点的链接方式。"],
  ["linear_list_operations", "linear_list_application", "实际线性表问题通过组合基本操作求解。"],
  ["sequential_list", "linear_list_application", "具体实现需要理解顺序表示及其基本操作。"],
  ["linked_list", "linear_list_application", "实际应用需要能实现和选用链式表示。"],
  ["abstract_data_type", "stack_queue_adt", "栈和队列同样通过规定操作及其行为来定义。"],
  ["stack_queue_adt", "stack", "栈的实现需要符合后进先出的接口约定。"],
  ["stack_queue_adt", "queue", "队列的实现需要符合先进先出的接口约定。"],
  ["stack", "stack_recursion", "用显式栈模拟递归前要会保存和取出状态。"],
  ["stack", "stack_queue_application", "栈应用依赖入栈、出栈和栈顶操作。"],
  ["queue", "stack_queue_application", "队列应用依赖入队、出队和队首操作。"],
  ["abstract_data_type", "tree", "树的抽象定义在数据结构及抽象数据类型的基础上建立。"],
  ["tree", "binary_tree_storage", "表示二叉树前要知道其左右孩子关系和结构性质。"],
  ["binary_tree_storage", "tree_recursive", "递归遍历需要读取左右孩子引用，构建过程依赖具体存储。"],
  ["binary_tree_storage", "tree_iterative", "非递归遍历需要按存储结构获取左右孩子。"],
  ["stack", "tree_iterative", "用栈保存遍历中待处理的节点，可实现深度优先的非递归遍历。"],
  ["tree_recursive", "tree_application", "二叉树应用依赖能够按所需次序访问树中节点。"],
  ["tree", "forest", "一般树、森林和二叉树之间的转换需要先理解树的定义。"],
  ["binary_tree_storage", "huffman_principles", "编码用到带权二叉树和从根到叶子的路径表示。"],
  ["huffman_principles", "huffman_algorithms", "了解最小权重合并和编码原理后才能实现构建算法。"],
  ["graph", "graph_traversal", "遍历时必须能从顶点枚举其邻接点。"],
  ["stack", "graph_traversal", "图的深度优先遍历可由显式栈保存待访问状态。"],
  ["queue", "graph_traversal", "图的广度优先遍历依赖队列保存待访问顶点。"],
  ["graph", "minimum_spanning_tree", "最小生成树基于带权边和图的连通性。"],
  ["graph", "topological_sort", "拓扑排序处理有向图中的顶点和先后依赖。"],
  ["topological_sort", "critical_path", "按拓扑次序计算最早和最晚事件时刻。"],
  ["graph", "shortest_path", "最短路径以图中边及权值为计算依据。"],
  ["algorithm_analysis", "searching", "教学要求分析静态查找算法的效率。"],
  ["tree", "dynamic_search", "二叉排序树和平衡树需建立在二叉树的基本定义上。"],
  ["sorting_basics", "sorting_ideas", "理解关键字、顺序等概念后可以区分不同排序思想。"],
  ["sorting_ideas", "sorting", "实现插入、交换、选择、归并时需理解对应算法思想。"],
  ["sorting", "sorting_comparison", "比较排序方法需要理解算法各自的行为。"],
  ["algorithm_analysis", "sorting_comparison", "比较排序算法的时空代价需要复杂度分析。"],
]);

// Cross-course prerequisites point from the introductory course to the advanced course.
addRelationships("prerequisite", [
  ["algorithm_design", "algorithm_analysis", "先能描述算法步骤，才能针对步骤和输入规模分析时空代价。"],
  ["single_loop", "algorithm_analysis", "循环体执行次数是入门课程分析时间复杂度的常见对象。"],
  ["array", "sequential_list", "顺序表把元素存入连续空间，通过数组下标定位。"],
  ["dynamic_memory", "linked_list", "链式线性表需要会定义节点、动态分配节点和释放节点。"],
  ["list_update", "linked_list", "链式线性表的基本算法沿用单链表插入与删除中的链接更新。"],
  ["list_update", "list_variants", "循环和双向链表的更新建立在对单链表链接修改的理解上。"],
  ["recursion", "stack_recursion", "用栈解释递归之前，需要熟悉一次实际的递归调用过程。"],
  ["struct", "binary_tree_storage", "二叉链表节点需要以结构体表示数据与左右链接。"],
  ["pointer", "binary_tree_storage", "二叉链表用指针保存左右子树的地址。"],
  ["recursion", "tree_recursive", "递归遍历通过分别处理左右子树来缩小问题规模。"],
  ["string", "graph", "邻接矩阵是二维数组在图存储中的应用，依赖二维下标。"],
  ["array_initialization", "searching", "顺序查找和折半查找需要能在数组上检查元素与移动下标。"],
  ["array_initialization", "sorting", "教学中的数组排序实现依赖访问、比较和交换数组元素。"],
]);

addRelationships("related", [
  ["program_execution", "sequence_io", "可以通过运行顺序计算示例检验输入输出格式。"],
  ["algorithm_design", "loop_design", "流程图可以展示循环条件与回到判断节点的路径。"],
  ["branch_statements", "loop_design", "循环也依赖判断，比较两者有助于理解选择与重复的区别。"],
  ["nested_loop", "string", "二维数组通常用行列两层循环逐项访问。"],
  ["function_application", "array_application", "可以将数组读取、处理和结果输出拆成独立函数。"],
  ["string", "pointer", "掌握指针以后可对比字符数组访问与字符指针访问。"],
  ["pointer_parameters", "list_application", "综合链表程序可借助指针参数封装修改节点的操作。"],
  ["list_application", "file_operations", "链表记录可保存到文件，再从文件恢复。"],
  ["sequential_list", "stack", "顺序栈可重用顺序表式的数组表示。"],
  ["linked_list", "queue", "链式队列可以用前后节点引用实现入队和出队。"],
  ["stack_recursion", "tree_iterative", "可以比较递归遍历的调用栈和非递归遍历的显式栈。"],
  ["graph_traversal", "minimum_spanning_tree", "遍历可用于探索连通部分，生成树则在此基础上加入权重目标。"],
  ["searching", "dynamic_search", "可比较有序表的静态查找和支持插入、删除的动态查找。"],
  ["dynamic_search", "hash_table", "可分别比较基于二叉树和基于散列的动态查找策略。"],
  ["searching", "sorting_ideas", "折半查找需要有序输入，排序可作为获取有序数据的手段。"],
  ["nested_loop", "sorting_ideas", "插入、选择和交换排序的典型写法常见嵌套循环。"],
  ["list_creation", "graph", "邻接表的一种实现为每个顶点动态建立邻接链表。"],
  ["list_traversal", "graph_traversal", "沿邻接链表扫描邻居与单链表顺序访问类似。"],
  ["array", "binary_tree_storage", "完全二叉树可用数组下标表达父子位置。"],
  ["recursion", "sorting", "归并排序常用递归实现拆分与合并，部分实现也可采用迭代。"],
  ["string", "hash_table", "字符串键是练习散列函数与冲突处理的一类常用输入。"],
]);

export { courses, points, edges };
