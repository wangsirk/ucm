/**
 * MIT License
 *
 * Copyright (c) 2025 Huawei Technologies Co., Ltd. All rights reserved.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
#ifndef UNIFIEDCACHE_LUSTRE_STORE_CC_LUSTRE_FILE_H
#define UNIFIEDCACHE_LUSTRE_STORE_CC_LUSTRE_FILE_H

#include <cstdint>
#include <string>
#include "status/status.h"

/**
 * LustreFile - Lustre 文件操作封装
 *
 * 提供统一的文件操作接口，支持：
 * - Lustre 条带化文件创建 (llapi_layout)
 * - 标准 POSIX 文件操作
 * - 异常安全保证
 */
namespace UC::LustreStore {

class LustreFile {
public:
    // ===== 构造/析构 =====

    /**
     * 构造函数
     * @param path 文件路径
     */
    explicit LustreFile(const std::string& path);

    /**
     * 析构函数 - 自动关闭文件
     *
     * 异常安全: 析构函数不抛异常
     */
    ~LustreFile();

    // 禁止拷贝和移动
    LustreFile(const LustreFile&) = delete;
    LustreFile& operator=(const LustreFile&) = delete;
    LustreFile(LustreFile&&) = delete;
    LustreFile& operator=(LustreFile&&) = delete;

    // ===== 文件创建 =====

    /**
     * 创建条带化文件 (Lustre API)
     *
     * 使用 llapi_layout 创建 Lustre 条带化文件
     *
     * @param stripeCount 条带数量 (0 = 文件系统默认)
     * @param stripeSize 条带大小 (字节，0 = 文件系统默认)
     * @param mode 文件权限
     * @return Status 操作状态
     */
    Status CreateStriped(int stripeCount, size_t stripeSize, mode_t mode = 0644);

    /**
     * 创建普通文件 (POSIX)
     *
     * @param flags 文件标志 (O_CREAT | O_WRONLY | O_EXCL)
     * @param mode 文件权限
     * @return Status 操作状态
     */
    Status CreateNormal(uint32_t flags, mode_t mode = 0644);

    // ===== 文件操作 =====

    /**
     * 打开文件
     *
     * @param flags 打开标志 (O_RDONLY, O_WRONLY, O_RDWR)
     * @return Status 操作状态
     */
    Status Open(uint32_t flags);

    /**
     * 读取文件
     *
     * @param buffer 缓冲区
     * @param size 读取大小
     * @param offset 文件偏移
     * @return Status 操作状态
     */
    Status Read(void* buffer, size_t size, off64_t offset);

    /**
     * 写入文件
     *
     * @param buffer 数据缓冲区
     * @param size 写入大小
     * @param offset 文件偏移
     * @return Status 操作状态
     */
    Status Write(const void* buffer, size_t size, off64_t offset);

    /**
     * 关闭文件
     *
     * 多次调用 Close() 是安全的
     */
    void Close();

    /**
     * 同步文件到磁盘
     *
     * @return Status 操作状态
     */
    Status Sync();

    // ===== 目录操作 =====

    /**
     * 创建目录 (静态方法)
     *
     * 递归创建目录结构
     *
     * @param path 目录路径
     * @param mode 目录权限
     * @return Status 操作状态
     */
    static Status MkDir(const std::string& path, mode_t mode = 0755);

    /**
     * 设置目录为条带化目录 (静态方法)
     *
     * 为目录设置 Lustre 条带化属性，该目录下创建的所有文件将自动继承条带属性。
     * 使用 llapi_dir_create() 创建带有条带属性的目录，这是 Lustre 推荐的目录条带化 API。
     *
     * 注意: llapi_dir_create() 会同时创建目录，调用前目录不应存在。
     *       如果目录已存在，函数会返回 EEXIST/EALREADY 但被视为成功。
     *
     * @param path 目录路径
     * @param stripeCount 条带数量 (0 = 不启用条带化)
     * @param stripeSize 条带大小 (字节，0 = 使用文件系统默认 1MB)
     * @param mode 目录权限
     * @return Status 操作状态
     */
    static Status SetStripedDirectory(const std::string& path,
                                      int stripeCount,
                                      size_t stripeSize,
                                      mode_t mode = 0755);

    /**
     * 检查文件/目录访问权限
     *
     * @param mode 访问模式 (F_OK, R_OK, W_OK, X_OK)
     * @return bool true=可访问, false=不可访问
     */
    bool Access(int32_t mode) const;

    // ===== 文件管理 =====

    /**
     * 重命名文件
     *
     * @param newName 新文件名
     * @return Status 操作状态
     */
    Status Rename(const std::string& newName);

    /**
     * 创建硬链接 (原子操作)
     *
     * 用于 CommitFile 的原子提交
     *
     * @param oldPath 旧路径
     * @param newPath 新路径
     * @return Status 操作状态
     *   - Status::OK(): 成功
     *   - Status::DuplicateKey(): 文件已存在 (EEXIST)
     *   - Status::IOError(): 其他错误
     */
    static Status Link(const std::string& oldPath, const std::string& newPath);

    /**
     * 删除文件 (静态方法)
     *
     * @param path 文件路径
     * @return Status 操作状态
     */
    static Status Remove(const std::string& path);

    /**
     * 检查文件是否存在 (静态方法)
     *
     * @param path 文件路径
     * @return bool true=存在, false=不存在
     */
    static bool Exists(const std::string& path);

    /**
     * 获取文件大小
     *
     * @return size_t 文件大小 (失败返回 0)
     */
    size_t GetSize() const;

    // ===== 状态查询 =====

    /**
     * 检查文件是否打开
     *
     * @return bool true=已打开, false=未打开
     */
    bool IsOpen() const { return fd_ >= 0; }

    /**
     * 获取文件描述符
     *
     * @return int 文件描述符 (-1 表示未打开)
     */
    int GetFd() const { return fd_; }

    /**
     * 获取文件路径
     *
     * @return const std::string& 文件路径
     */
    const std::string& GetPath() const { return path_; }

private:
    std::string path_;     // 文件路径
    int fd_;               // 文件描述符 (-1=未打开)

    // 辅助函数
    Status CheckOpen() const;
};

}  // namespace UC::LustreStore

#endif  // UNIFIEDCACHE_LUSTRE_STORE_CC_LUSTRE_FILE_H
