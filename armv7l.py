from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, List, Optional, Tuple, Union

try:
  Reg  # type: ignore[name-defined]
  Ops  # type: ignore[name-defined]
except NameError:
  # Fallback minimal enums (only for standalone testing). Remove if you provide your own.
  class Reg(Enum):
    r0=0; r1=1; r2=2; r3=3; r4=4; r5=5; r6=6; r7=7; r8=8; r9=9; r10=10; r11=11; r12=12; sp=13; lr=14; pc=15
    def __str__(self): return self.name.upper()

  class Ops(Enum):
    MOV=1; MVN=2; ADD=3; ADC=4; SUB=5; SBC=6; RSB=7; RSC=8; MUL=9; MLA=10
    AND=11; ORR=12; EOR=13; BIC=14; LSL=15; LSR=16; ASR=17; ROR=18; RRX=19
    LDR=20; STR=21; LDRB=22; STRB=23; LDRH=24; LDRSH=25; LDM=26; STM=27
    SVC=28; NOP=29; SWP=30; B=31; BL=32; BX=33; PUSH=34; POP=35
    def __str__(self): return self.name

# Condition codes ----------------------------------------------------------------
class Cond(Enum):
  AL = ""   # default (always)
  EQ = "EQ"; NE = "NE"; CS = "CS"; CC = "CC"; MI = "MI"; PL = "PL"
  VS = "VS"; VC = "VC"; HI = "HI"; LS = "LS"; GE = "GE"; LT = "LT"; GT = "GT"; LE = "LE"
  def __str__(self) -> str: return self.value

# Operands -----------------------------------------------------------------------
Number = int

@dataclass(frozen=True)
class Imm:
  value: Number
  def __str__(self) -> str: return f"#{self.value}"

@dataclass(frozen=True)
class Shift:
  kind: str  # LSL/LSR/ASR/ROR
  amount: Number
  def __str__(self) -> str: return f"{self.kind} #{self.amount}"

@dataclass(frozen=True)
class Mem:
  base: Reg
  offset: Optional[Union[Number, Reg]] = None
  shift: Optional[Shift] = None
  pre_indexed: bool = True
  write_back: bool = False

  def __str__(self) -> str:
    # [Rn], #imm / [Rn, #imm]! / [Rn, Rm, shift] variants
    parts: List[str] = [str(self.base)]
    if self.offset is not None:
      if isinstance(self.offset, int): parts.append(f"#{self.offset}")
      else: parts.append(str(self.offset))
      if self.shift is not None: parts.append(str(self.shift))
    inside = ", ".join(parts)
    if self.pre_indexed:
      wb = "!" if self.write_back else ""
      return f"[{inside}]{wb}"
    else:
      # post-indexed: [Rn], #imm or [Rn], Rm
      if self.offset is None: raise ValueError("post-indexed addressing requires an offset")
      off = f"#{self.offset}" if isinstance(self.offset, int) else str(self.offset)
      if self.shift is not None: off = f"{off}, {self.shift}"
      return f"[{str(self.base)}], {off}"

# Helpers ------------------------------------------------------------------------
ImmLike = Union[int, Imm]
RegLike = Union[Reg, str]
Opnd = Union[Reg, Imm, Mem, str]


def imm(x: ImmLike) -> Imm: return x if isinstance(x, Imm) else Imm(int(x))


def lsl(amount: int) -> Shift: return Shift("LSL", amount)


def lsr(amount: int) -> Shift: return Shift("LSR", amount)


def asr(amount: int) -> Shift: return Shift("ASR", amount)


def ror(amount: int) -> Shift: return Shift("ROR", amount)


def mem(base: Reg, offset: Optional[Union[int, Reg]] = None, *, shift_: Optional[Shift] = None,
        pre: bool = True, wb: bool = False) -> Mem:
  return Mem(base, offset, shift_, pre, wb)

# Emitter ------------------------------------------------------------------------
@dataclass
class Instr:
  op: Ops
  operands: Tuple[Opnd, ...] = ()
  cond: Cond = Cond.AL
  setflags: bool = False
  comment: Optional[str] = None

  def __str__(self) -> str:
    op = str(self.op)
    # condition + S flag
    cond = str(self.cond)
    sfx = "S" if self.setflags and op not in {"LDR", "STR", "LDRB", "STRB", "LDM", "STM", "B", "BL", "BX"} else ""
    mnem = op + cond + sfx
    ops = ", ".join(str(o) for o in self.operands)
    line = f"{mnem} {ops}".rstrip()
    if self.comment:
      pad = " " if ops else ""
      line += f"{pad}; {self.comment}"
    return line

class Asm:
  def __init__(self) -> None: self.lines: List[str] = []
  @staticmethod 
  def initial() -> Asm:
    asm = Asm()
    asm.directive(".section .text")
    asm.global_("_start")
    asm.label("_start")
    return asm

  # --- Low-level emitter -------------------------------------------------
  def emit(self, op: Ops, *operands: Opnd, cond: Cond = Cond.AL, s: bool = False, cmt: Optional[str] = None) -> None:
    self.lines.append(str(Instr(op, operands, cond, s, cmt)))

  def label(self, name: str) -> None:
    if not name or any(ch.isspace() for ch in name): raise ValueError("label must be a non-empty identifier without spaces")
    self.lines.append(f"{name}:")

  def directive(self, text: str) -> None:
    self.lines.append(text)

  def comment(self, text: str) -> None:
    self.lines.append(f"# {text}")

  def global_(self, name: str) -> None:
    self.lines.append(f".global {name}")

  # --- Common instruction helpers ---------------------------------------
  def mov(self, rd: Reg, src: Union[Reg, ImmLike], *, cond: Cond = Cond.AL, s: bool = False, cmt: Optional[str] = None) -> None:
    self.emit(Ops.MOV, rd, imm(src) if isinstance(src, int) else src, cond=cond, s=s, cmt=cmt)

  def add(self, rd: Reg, rn: Reg, op2: Union[Reg, ImmLike, Tuple[Reg, Shift]], *, cond: Cond = Cond.AL, s: bool = False) -> None:
    self._dataproc(Ops.ADD, rd, rn, op2, cond, s)

  def sub(self, rd: Reg, rn: Reg, op2: Union[Reg, ImmLike, Tuple[Reg, Shift]], *, cond: Cond = Cond.AL, s: bool = False) -> None:
    self._dataproc(Ops.SUB, rd, rn, op2, cond, s)

  def and_(self, rd: Reg, rn: Reg, op2: Union[Reg, ImmLike, Tuple[Reg, Shift]], *, cond: Cond = Cond.AL, s: bool = False) -> None:
    self._dataproc(Ops.AND, rd, rn, op2, cond, s)

  def orr(self, rd: Reg, rn: Reg, op2: Union[Reg, ImmLike, Tuple[Reg, Shift]], *, cond: Cond = Cond.AL, s: bool = False) -> None:
    self._dataproc(Ops.ORR, rd, rn, op2, cond, s)

  def eor(self, rd: Reg, rn: Reg, op2: Union[Reg, ImmLike, Tuple[Reg, Shift]], *, cond: Cond = Cond.AL, s: bool = False) -> None:
    self._dataproc(Ops.EOR, rd, rn, op2, cond, s)

  def _dataproc(self, op: Ops, rd: Reg, rn: Reg, op2: Union[Reg, ImmLike, Tuple[Reg, Shift]], cond: Cond, s: bool) -> None:
    if isinstance(op2, int): self.emit(op, rd, rn, imm(op2), cond=cond, s=s)
    elif isinstance(op2, tuple):
      rm, sh = op2
      self.emit(op, rd, rn, str(rm) + ", " + str(sh))
    else: self.emit(op, rd, rn, op2, cond=cond, s=s)

  def ldr(self, rd: Reg, address: Mem, *, cond: Cond = Cond.AL) -> None:
    self.emit(Ops.LDR, rd, address, cond=cond)

  def str(self, rd: Reg, address: Mem, *, cond: Cond = Cond.AL) -> None:
    self.emit(Ops.STR, rd, address, cond=cond)

  def strb(self, rd: Reg, address: Mem, *, cond: Cond = Cond.AL) -> None:
    self.emit(Ops.STRB, rd, address, cond=cond)

  def b(self, target: str, *, cond: Cond = Cond.AL) -> None:
    self.emit(Ops.B, target, cond=cond)

  def bl(self, target: str, *, cond: Cond = Cond.AL) -> None:
    op = Ops.BL if hasattr(Ops, "BL") else Ops.B  # fallback if enum lacks BL
    self.emit(op, target, cond=cond)

  def bx(self, rm: Reg, *, cond: Cond = Cond.AL) -> None:
    op = Ops.BX if hasattr(Ops, "BX") else Ops.B
    self.emit(op, rm, cond=cond)
  
  def push(self, regs: List[Reg], *, cond: Cond = Cond.AL) -> None:
    # PUSH is STMDB SP!, {reglist}
    reglist = "{" + ", ".join(str(r) for r in regs) + "}"
    self.emit(Ops.PUSH, reglist, cond=cond)

  def pop(self,regs:List[Reg],*,cond:Cond = Cond.AL) ->None:
    reglist = "{" + ", ".join(str(r) for r in regs) + "}"
    self.emit(Ops.PUSH, reglist, cond=cond)

  def svc(self): self.emit(Ops.SVC,"#0")

  # --- Output ------------------------------------------------------------
  def text(self) -> str: return "\n".join(self.lines) + ("\n" if self.lines and not self.lines[-1].endswith("\n") else "")

  def clear(self) -> None: self.lines.clear()
  
class Syscall:
  @staticmethod
  def write(asm:Asm,size:int):
    asm.mov(Reg.r7,4)
    asm.mov(Reg.r0,1)
    asm.mov(Reg.r1,Reg.sp)
    asm.mov(Reg.r2,size)
    asm.svc()

  @staticmethod
  def exit(asm:Asm):
    asm.mov(Reg.r7,1)
    asm.mov(Reg.r0,1)
    asm.svc()

def print_asm(text:Any) -> Asm:
  text = str(text) if not isinstance(text,str) else text
  n_size = int(((len(text) + 15) / 16) * 16)
  asm = Asm.initial()
  asm.mov(Reg.r3,Reg.sp)
  asm.sub(Reg.sp,Reg.sp,n_size)
  asm.comment(f"Allocated Stack : {n_size}")
  for idx,t in enumerate(text):
    asm.mov(Reg.r1,ord(t))
    asm.strb(Reg.r1,Mem(Reg.sp,idx))
  asm.mov(Reg.r1,ord('\n'))
  asm.strb(Reg.r1,Mem(Reg.sp,idx+1))
  Syscall.write(asm,len(text)+1)
  asm.comment(f"Deallocated stack")
  asm.add(Reg.sp,Reg.sp,n_size) # deallocated stack
  Syscall.exit(asm)
  return asm

def int_to_asciz(value:int):
  asm = Asm.initial()
  asm.mov(Reg.r1,value)
  asm.add(Reg.r1,Reg.r1,48)
  asm.sub(Reg.sp,Reg.sp,2)
  asm.strb(Reg.r1,Mem(Reg.sp,0))
  asm.mov(Reg.r1,ord('\n'))
  asm.strb(Reg.r1,Mem(Reg.sp,1))
  Syscall.write(asm,2)
  asm.add(Reg.sp,Reg.sp,2)
  Syscall.exit(asm)
  return asm


if __name__ == "__main__":
  asm = print_asm(11119810238918329)
  print(asm.text())
  
  
  
  

