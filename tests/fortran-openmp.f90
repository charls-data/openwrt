program smoke
  use omp_lib
  use ieee_arithmetic
  implicit none
  integer :: total, i
  real(kind=16) :: x
  total = 0
!$omp parallel do reduction(+:total)
  do i = 1, 100
    total = total + i
  end do
!$omp end parallel do
  if (total /= 5050) stop 1
  x = sqrt(2.0_16)
  if (abs(x*x - 2.0_16) > 1.0e-30_16) stop 2
  if (.not. ieee_is_finite(1.0)) stop 3
  print *, 'Fortran/OpenMP/quad precision OK', total, x
end program smoke

