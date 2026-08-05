# ADR-002：DSL、IR 与包版本独立演进

- 状态：Accepted
- 日期：2026-08-05

## 决策

DSL 使用 `graphgpt.dev/v1alpha1`，IR 使用独立 `ir_version`，Python 包遵循 SemVer。任何外部
框架对象都不能进入可序列化 IR。

## 后果

Web 编辑器、迁移器与多语言编译器可以围绕稳定 IR 协作，但需要显式迁移和兼容矩阵。

