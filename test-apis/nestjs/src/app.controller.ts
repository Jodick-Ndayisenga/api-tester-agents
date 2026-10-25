import {
  Body, Controller, Delete, Get, Headers, HttpException, HttpStatus,
  Param, Post, Put, Query,
} from "@nestjs/common";
import { IsEmail, IsString, Length } from "class-validator";

class UserInput {
  @IsString()
  @Length(2, 80)
  name!: string;

  @IsEmail()
  email!: string;
}

type User = UserInput & { id: number };

@Controller()
export class AppController {
  private readonly users = new Map<number, User>([
    [1, { id: 1, name: "Ada Lovelace", email: "ada@example.com" }],
    [2, { id: 2, name: "Grace Hopper", email: "grace@example.com" }],
  ]);

  @Get("health")
  health() { return { status: "ok", service: "nestjs-fixture" }; }

  @Get("api/v1/users")
  listUsers(@Query("limit") limit = "20") {
    return [...this.users.values()].slice(0, Math.min(Number(limit) || 20, 100));
  }

  @Get("api/v1/users/:id")
  getUser(@Param("id") id: string) {
    const user = this.users.get(Number(id));
    if (!user) throw new HttpException("User not found", HttpStatus.NOT_FOUND);
    return user;
  }

  @Post("api/v1/users")
  createUser(@Body() payload: UserInput) {
    const id = Math.max(...this.users.keys()) + 1;
    const user = { id, name: payload.name, email: payload.email };
    this.users.set(id, user);
    return user;
  }

  @Put("api/v1/users/:id")
  updateUser(@Param("id") id: string, @Body() payload: UserInput) {
    const numericId = Number(id);
    if (!this.users.has(numericId)) throw new HttpException("User not found", HttpStatus.NOT_FOUND);
    const user = { id: numericId, name: payload.name, email: payload.email };
    this.users.set(numericId, user);
    return user;
  }

  @Delete("api/v1/users/:id")
  deleteUser(@Param("id") id: string) {
    const numericId = Number(id);
    if (!this.users.delete(numericId)) throw new HttpException("User not found", HttpStatus.NOT_FOUND);
    return { deleted: true, id: numericId };
  }

  @Get("api/v1/search")
  search(@Query("q") query?: string) {
    if (!query || query.length < 2) throw new HttpException("q is required", HttpStatus.BAD_REQUEST);
    return { query, results: [...this.users.values()].filter((user) => user.name.toLowerCase().includes(query.toLowerCase())) };
  }

  @Get("api/v1/admin/secret")
  adminSecret(@Headers("authorization") authorization?: string) {
    if (authorization !== "Bearer test-token") throw new HttpException("Bearer token required", HttpStatus.UNAUTHORIZED);
    return { message: "admin access granted" };
  }

  @Get("api/v1/buggy")
  buggy() { throw new HttpException("Intentional fixture failure", HttpStatus.INTERNAL_SERVER_ERROR); }

  @Get("api/v1/slow")
  async slow(@Query("delay_ms") delay = "100") {
    const delayMs = Math.min(Number(delay) || 100, 5000);
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    return { delay_ms: delayMs };
  }
}
